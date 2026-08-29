"""Prototype: AI Ingest v2 — per-chunk extract → match → AI-merge (terms + relations).

For each chunk (Section) in order:
  step1. AI extract terms + deterministic extract terms -> new_terms
  step2. dict matching + embedding matching (for terms found in step1) -> existing candidates
  step3. AI merge of step1+2 -> ADD vs MERGE(target)
  -- same 3 steps for relations --
  step4. update dict + ontology + term/rel indexes (incremental)

Run:
  .venv/bin/python prototypes/ai-ingest-v2/ingest_v2.py \
    --parsed data/parsed/38300-i30.jsonl --base-dict data/dict.json --base-ontology data/ontology.json \
    --dict /tmp/v2_dict.json --ontology /tmp/v2_ontology.json --limit 100 --app-config config/app.yaml

Checkpointed + resumable (--resume). LLM optional: when llm.enabled=false the
merge judges fall back to deterministic safe rules (no false merges). Embed
defaults to hash (CPU-only, no model download).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Allow imports when run as `python prototypes/ai-ingest-v2/ingest_v2.py`
_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2] if (_HERE / "ingest_v2.py").exists() else Path.cwd()
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
# For relative imports inside prototypes/ai_ingest legacy helpers when needed
_LEGACY = _REPO / "prototypes" / "ai_ingest"
if str(_LEGACY) not in sys.path:
    sys.path.insert(0, str(_LEGACY))

from onto3gpp.app_config import load_app_config  # noqa: E402
from onto3gpp.compile.dictionary import Dictionary, DictionaryEntry, build_automaton  # noqa: E402
from onto3gpp.embed import EmbeddingIndex, get_embedder  # noqa: E402
from onto3gpp.extract.relations import extract_relations  # noqa: E402
from onto3gpp.extract.terms import extract_candidates  # noqa: E402
from onto3gpp.ingest.merge_judge import MergeJudge  # noqa: E402
from onto3gpp.llm import LLMClient  # noqa: E402
from onto3gpp.ontology.schema import Concept, Ontology, Relation  # noqa: E402
from onto3gpp.ontology.schema import ontology_from_dict, ontology_to_dict, validate_ontology  # noqa: E402
from onto3gpp.parser import Section  # noqa: E402

try:
    from onto3gpp.llm.queue import ModelQueue  # noqa: E402
except Exception:  # pragma: no cover
    ModelQueue = None  # type: ignore

CONCEPT_TYPES = (
    "network_function, procedure, information_element, interface, protocol, "
    "qos, architecture, security"
)

EXTRACT_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the specification text below, identify NEW technical concepts (terms).

Text:
{text}

List each concept with its type (choose from: {types}) and a confidence 0-1. Return ONLY a JSON object of the form:
{{"concepts": [{{"canonical": "term", "type": "type", "confidence": 0.9}}]}}"""

RELATIONS_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the text below, propose relations between technical concepts.

The existing knowledge base already contains these relations:
{known_relations}

The deterministic extractor found these candidate relations:
{candidate_relations}

Text:
{text}

Return ONLY a JSON object of the form:
{{"relations": [{{"source": "term", "rel": "uses", "target": "term", "confidence": 0.9}}]}}
Use relation types like: uses, connects, carries, handles, establishes, forwards, selects, maps, applies, initiates, moves, updates, is_a. Only include relations you are confident about."""

# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def load_sections(parsed: Path) -> list[Section]:
    sections: list[Section] = []
    for line in parsed.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        sections.append(Section(
            spec=data["spec"], release=data["release"], clause=data["clause"],
            title=data["title"], text=data["text"],
            parent_clause=data.get("parent_clause", ""),
            metadata=data.get("metadata", {}),
        ))
    return sections


def load_dict(path: Path) -> Dictionary:
    return Dictionary.from_dict(json.loads(path.read_text(encoding="utf-8")))


def load_ontology(path: Path) -> Ontology:
    return ontology_from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_dict(d: Dictionary, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d.to_dict(), indent=2), encoding="utf-8")


def save_ontology(o: Ontology, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ontology_to_dict(o), indent=2), encoding="utf-8")


def _fmt_relations(rels) -> str:
    if not rels:
        return "(none)"
    return "\n".join(f"- {r.source} --{r.rel}--> {r.target}" for r in rels)

# ---------------------------------------------------------------------------
# Indexes
# ---------------------------------------------------------------------------

def build_term_index(onto: Ontology, embedder) -> EmbeddingIndex:
    idx = EmbeddingIndex(dim=embedder.dim, embedder=embedder)
    if onto.concepts:
        idx.add_many([(c.id, c.canonical) for c in onto.concepts])
    return idx


def build_rel_index(onto: Ontology, embedder) -> EmbeddingIndex:
    idx = EmbeddingIndex(dim=embedder.dim, embedder=embedder)
    if onto.relations:
        # Use fresh embedder copy to keep same dim but separate id space
        # Keys are "source rel target" strings; id is f"{source}|{rel}|{target}"
        items = []
        for r in onto.relations:
            rid = f"{r.source}|{r.rel}|{r.target}"
            txt = f"{r.source} {r.rel} {r.target}"
            items.append((rid, txt))
        idx.add_many(items)
    return idx

# ---------------------------------------------------------------------------
# Step 1 — extract (deterministic + AI union)
# ---------------------------------------------------------------------------

def ai_extract_terms(section: Section, client: LLMClient | None, max_chars: int = 800,
                     retries: list | None = None) -> list[dict]:
    if client is None or not client.config.enabled:
        return []
    # Use llm helpers with litellm directly via client.complete_json
    prompt = EXTRACT_PROMPT_TEMPLATE.format(text=section.text[:max_chars], types=CONCEPT_TYPES)
    # Retry loop mirroring ai_helpers.complete_json but via LLMClient
    import json as _json, re as _re, time as _time
    attempts = 5
    last_err = None
    for n in range(1, attempts + 1):
        try:
            text = client.complete(prompt)
            if not text:
                continue
            # extract json
            t = text.strip()
            fence = _re.search(r"```(?:json)?\s*(.*?)```", t, _re.DOTALL)
            if fence:
                t = fence.group(1).strip()
            # find balanced object
            start = t.find("{")
            if start == -1:
                raise ValueError("no JSON")
            depth = 0
            end = -1
            for i in range(start, len(t)):
                if t[i] == "{":
                    depth += 1
                elif t[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end == -1:
                raise ValueError("unbalanced JSON")
            data = _json.loads(t[start:end+1])
            if retries is not None:
                retries.append(n)
            return data.get("concepts", [])
        except Exception as e:  # noqa: BLE001
            last_err = e
            _time.sleep(0.05)
    if retries is not None:
        retries.append(attempts)
    # graceful fallback: no AI concepts
    return []


def ai_extract_relations(section: Section, known_rels, candidate_rels,
                         client: LLMClient | None, max_chars: int = 800,
                         retries: list | None = None) -> list[dict]:
    if client is None or not client.config.enabled:
        return []
    prompt = RELATIONS_PROMPT_TEMPLATE.format(
        text=section.text[:max_chars],
        known_relations=_fmt_relations(known_rels),
        candidate_relations=_fmt_relations(candidate_rels),
    )
    import json as _json, re as _re, time as _time
    attempts = 5
    for n in range(1, attempts + 1):
        try:
            text = client.complete(prompt)
            if not text:
                continue
            t = text.strip()
            fence = _re.search(r"```(?:json)?\s*(.*?)```", t, _re.DOTALL)
            if fence:
                t = fence.group(1).strip()
            start = t.find("{")
            if start == -1:
                raise ValueError("no JSON")
            depth = 0
            end = -1
            for i in range(start, len(t)):
                if t[i] == "{":
                    depth += 1
                elif t[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end == -1:
                raise ValueError("unbalanced")
            data = _json.loads(t[start:end+1])
            if retries is not None:
                retries.append(n)
            return data.get("relations", [])
        except Exception:  # noqa: BLE001
            _time.sleep(0.05)
    if retries is not None:
        retries.append(attempts)
    return []


def step1_terms(section: Section, onto: Ontology, extract_client: LLMClient | None,
                max_chars: int = 800) -> tuple[list, dict]:
    """Deterministic + AI union for terms. Returns (new_terms, meta)."""
    cand = extract_candidates([section])
    # Convert deterministic to dict-like for union
    det_map: dict[str, dict] = {}
    for c in cand:
        key = c.canonical.strip().lower()
        if not key:
            continue
        det_map[key] = {"canonical": c.canonical.strip(), "type": c.type, "confidence": c.confidence, "aliases": list(c.aliases)}
    retries: list[int] = []
    ai_list = ai_extract_terms(section, extract_client, max_chars=max_chars, retries=retries)
    for t in ai_list:
        can = (t.get("canonical") or "").strip()
        if not can:
            continue
        key = can.lower()
        ctype = t.get("type") or "concept"
        conf = float(t.get("confidence", 0.5) or 0.5)
        # keep highest confidence
        if key not in det_map or conf > det_map[key].get("confidence", 0):
            det_map[key] = {"canonical": can, "type": ctype, "confidence": conf, "aliases": []}
        # else keep existing but maybe upgrade type if higher conf
    new_terms = list(det_map.values())
    meta = {"det": len(cand), "ai": len(ai_list), "union": len(new_terms), "retries": retries[0] if retries else 0}
    return new_terms, meta


def step1_relations(section: Section, onto: Ontology, relations_client: LLMClient | None,
                   max_chars: int = 800) -> tuple[list[Relation], dict]:
    """Deterministic + AI union for relations. Returns (new_relations, meta)."""
    cand_rels = extract_relations([section], onto)
    known_rels = [r for r in onto.relations if r.source in {c.id for c in onto.concepts}][:20]
    retries: list[int] = []
    ai_list = ai_extract_relations(section, known_rels, cand_rels, relations_client, max_chars=max_chars, retries=retries)
    # Map AI relation dicts -> Relation objects filtering to known concepts
    concept_ids = {c.id for c in onto.concepts}
    # also allow canonical lookup: ai may use canonical strings, map via id normalization
    id_by_canonical = {c.canonical.lower(): c.id for c in onto.concepts}
    canon_by_id = {c.id: c.canonical for c in onto.concepts}
    # include new term ids that may have been added in term step caller will have updated onto before calling
    # so this function should be called AFTER term decisions are staged.

    ai_rels: list[Relation] = []
    for r in ai_list:
        src = (r.get("source") or "").strip()
        tgt = (r.get("target") or "").strip()
        rel = (r.get("rel") or "").strip()
        if not src or not tgt or not rel:
            continue
        # resolve source/target to ids via canonical or id
        sid = src.lower().replace(" ", "_")
        tid = tgt.lower().replace(" ", "_")
        # try id direct, then canonical map, then raw
        if sid not in concept_ids:
            sid = id_by_canonical.get(src.lower()) or sid
        if tid not in concept_ids:
            tid = id_by_canonical.get(tgt.lower()) or tid
        if sid not in concept_ids or tid not in concept_ids:
            continue
        ai_rels.append(Relation(source=sid, rel=rel, target=tid, confidence=float(r.get("confidence", 0.8) or 0.8)))

    # Union dedup by (source,rel,target)
    seen: dict[tuple[str,str,str], Relation] = {}
    for r in cand_rels:
        seen[(r.source, r.rel, r.target)] = r
    for r in ai_rels:
        key = (r.source, r.rel, r.target)
        if key not in seen or r.confidence > seen[key].confidence:
            seen[key] = r
    new_relations = list(seen.values())
    meta = {"det": len(cand_rels), "ai": len(ai_rels), "union": len(new_relations), "retries": retries[0] if retries else 0}
    return new_relations, meta

# ---------------------------------------------------------------------------
# Step 2 — retrieval (dict exact + embedding)
# ---------------------------------------------------------------------------

def neighbours_for_terms(new_terms: list[dict], onto: Ontology,
                         term_index: EmbeddingIndex, threshold: float = 0.25,
                         top_k: int = 5, dictionary: Dictionary | None = None) -> dict[str, list[dict]]:
    """For each new term canonical -> list of neighbour dicts {id,canonical,type,cosine}.

    Hybrid retrieval (step 2): dict exact (normalized + compact + id-folded, cosine 1.0)
    UNION embedding top-k (thresholded). Uses batched embedding (search_texts)
    so GGUF models do one model call per chunk, not one per term.
    """
    id_to_can = {c.id: c.canonical for c in onto.concepts}
    id_to_type = {c.id: c.type for c in onto.concepts}
    # normalized + compact maps: exact lexical catch without embed
    from onto3gpp.ingest.merge_judge import _compact as _compact, _normalize as _norm
    norm_to_ids: dict[str, list[str]] = {}
    compact_to_ids: dict[str, list[str]] = {}
    for c in onto.concepts:
        n = _norm(c.canonical)
        norm_to_ids.setdefault(n, []).append(c.id)
        cn = _compact(c.canonical)
        compact_to_ids.setdefault(cn, []).append(c.id)
    # Pre-collect exact neighbours (no embedding needed) and texts needing embedding
    exact_maps: dict[str, dict[str, dict]] = {}
    need_embed: list[str] = []
    for t in new_terms:
        can = t["canonical"]
        n = _norm(can)
        cn = _compact(can)
        neighbours: dict[str, dict] = {}
        for nid in norm_to_ids.get(n, []):
            neighbours[nid] = {"id": nid, "canonical": id_to_can[nid], "type": id_to_type.get(nid, "concept"), "cosine": 1.0}
        for nid in compact_to_ids.get(cn, []):
            if nid not in neighbours:
                neighbours[nid] = {"id": nid, "canonical": id_to_can[nid], "type": id_to_type.get(nid, "concept"), "cosine": 1.0}
        lid = can.lower().replace(" ", "_").replace("-", "_")
        if lid in id_to_can and lid not in neighbours:
            neighbours[lid] = {"id": lid, "canonical": id_to_can[lid], "type": id_to_type.get(lid, "concept"), "cosine": 1.0}
        exact_maps[can] = neighbours
        need_embed.append(can)
    # Batch embed + search in one model call (critical for GGUF/CPU)
    batch_hits: dict[str, list[tuple[str, float]]] = {}
    if need_embed and len(term_index.ids) > 0:
        try:
            if hasattr(term_index, "search_texts"):
                all_hits = term_index.search_texts(need_embed, top_k=top_k, threshold=threshold)
                for can, hits in zip(need_embed, all_hits):
                    batch_hits[can] = hits
            else:
                for can in need_embed:
                    batch_hits[can] = term_index.search_text(can, top_k=top_k, threshold=threshold)
        except Exception:
            pass
    out: dict[str, list[dict]] = {}
    for t in new_terms:
        can = t["canonical"]
        neighbours = dict(exact_maps[can])
        n = _norm(can)
        for hid, cos in batch_hits.get(can, []):
            if hid in neighbours:
                continue
            neighbours[hid] = {"id": hid, "canonical": id_to_can.get(hid, hid), "type": id_to_type.get(hid, "concept"), "cosine": cos}
        lst = sorted(neighbours.values(), key=lambda d: d["cosine"], reverse=True)[: max(top_k, len(norm_to_ids.get(n, [])))]
        out[can] = lst
    return out


def neighbours_for_relations(new_rels: list[Relation], rel_index: EmbeddingIndex,
                             threshold: float = 0.25, top_k: int = 5) -> dict[tuple, list[dict]]:
    """For each new relation -> neighbour relations (id, source,rel,target, cosine).

    Batched: one embed call per chunk when possible.
    """
    if not new_rels:
        return {}
    txts = [f"{r.source} {r.rel} {r.target}" for r in new_rels]
    batch_hits: list[list[tuple[str, float]]] = []
    if len(rel_index.ids) > 0:
        try:
            if hasattr(rel_index, "search_texts"):
                batch_hits = rel_index.search_texts(txts, top_k=top_k, threshold=threshold)
            else:
                batch_hits = [rel_index.search_text(t, top_k=top_k, threshold=threshold) for t in txts]
        except Exception:
            batch_hits = [[] for _ in txts]
    else:
        batch_hits = [[] for _ in txts]
    out: dict[tuple, list[dict]] = {}
    for r, hits in zip(new_rels, batch_hits):
        txt = f"{r.source} {r.rel} {r.target}"
        neigh: list[dict] = []
        seen: set[str] = set()
        rid = f"{r.source}|{r.rel}|{r.target}"
        if rid in rel_index._id_to_idx:
            neigh.append({"id": rid, "source": r.source, "rel": r.rel, "target": r.target, "cosine": 1.0})
            seen.add(rid)
        for hid, cos in hits:
            if hid in seen:
                continue
            parts = hid.split("|")
            src = parts[0] if len(parts) > 0 else hid
            rel = parts[1] if len(parts) > 1 else ""
            tgt = parts[2] if len(parts) > 2 else ""
            neigh.append({"id": hid, "source": src, "rel": rel, "target": tgt, "cosine": cos})
        neigh = sorted(neigh, key=lambda d: d["cosine"], reverse=True)[:top_k]
        out[(r.source, r.rel, r.target)] = neigh
    return out

# ---------------------------------------------------------------------------
# Step 3 — AI merge judges
# ---------------------------------------------------------------------------

class RelMergeJudge:
    """Deterministic exact for relations; LLM optional mirroring MergeJudge shape."""

    def __init__(self, llm_client=None) -> None:
        self.llm_client = llm_client
        self._llm_available = False
        if llm_client is not None:
            try:
                cfg = getattr(llm_client, "config", None)
                if cfg is not None:
                    self._llm_available = bool(getattr(cfg, "enabled", False))
                else:
                    self._llm_available = bool(getattr(llm_client, "enabled", False))
            except Exception:
                self._llm_available = False

    @staticmethod
    def _norm_endpoint(s: str) -> str:
        import re as _re
        t = (s or "").casefold().replace("-", " ").replace("_", " ")
        t = _re.sub(r"\s+", " ", t).strip()
        return " ".join(sorted(t.split()))

    @staticmethod
    def _compact_endpoint(s: str) -> str:
        return (s or "").casefold().replace("-", "").replace("_", "").replace(" ", "").strip()

    def judge(self, new_rel: Relation, neighbours: list[dict]) -> dict:
        if not neighbours:
            return {"decision": "ADD", "target": None, "reason": "no neighbours"}
        # deterministic: same triple (case/hyphen/space tolerant) -> MERGE
        n_src = self._norm_endpoint(new_rel.source)
        n_rel = (new_rel.rel or "").casefold().strip()
        n_tgt = self._norm_endpoint(new_rel.target)
        c_src = self._compact_endpoint(new_rel.source)
        c_tgt = self._compact_endpoint(new_rel.target)
        for nb in neighbours:
            nb_src = nb.get("source", "")
            nb_rel = (nb.get("rel", "") or "").casefold().strip()
            nb_tgt = nb.get("target", "")
            if nb_rel != n_rel:
                continue
            nb_n_src = self._norm_endpoint(nb_src)
            nb_n_tgt = self._norm_endpoint(nb_tgt)
            nb_c_src = self._compact_endpoint(nb_src)
            nb_c_tgt = self._compact_endpoint(nb_tgt)
            if (nb_n_src == n_src and nb_n_tgt == n_tgt) or (nb_c_src == c_src and nb_c_tgt == c_tgt):
                return {"decision": "MERGE", "target": nb["id"], "reason": "normalized triple match"}
        if not self._llm_available or self.llm_client is None:
            return {"decision": "ADD", "target": None, "reason": "no exact triple"}
        # LLM path for relation near-duplicates (e.g. alias source/target variants already normalized to same ids would have matched; so only semantic near-miss like rel synonym)
        nb_lines = "\n".join(
            f'- id={nb["id"]!r} triple=({nb.get("source")} --{nb.get("rel")}--> {nb.get("target")}) cosine={nb.get("cosine",0):.3f}'
            for nb in neighbours
        )
        prompt = (
            "You are a 3GPP ontology relation merge judge. Decide if a newly extracted relation "
            "is the SAME as one of the existing neighbour relations (MERGE) or a distinct relation (ADD). "
            "Be conservative: different relation types or different endpoints are DISTINCT; "
            "hyphen/space/case variants of endpoint names ARE the same if they refer to the same concept.\n\n"
            f"New relation: ({new_rel.source} --{new_rel.rel}--> {new_rel.target})\n"
            f"Neighbours:\n{nb_lines}\n\n"
            'Reply with JSON only: {"decision": "MERGE"|"ADD", "target": "<id or null>", "reason": "..."}'
        )
        try:
            client = self.llm_client
            text = None
            if hasattr(client, "complete"):
                try:
                    text = client.complete(prompt)
                except TypeError:
                    text = client.complete(prompt, model=getattr(client.config, "model", "default"))  # type: ignore
            elif hasattr(client, "_call"):
                text = client._call(prompt)
            elif callable(client):
                text = client(prompt)
            else:
                raise RuntimeError("LLM client has no known call method")
            import re as _re, json as _json
            m = _re.search(r"\{.*\}", text or "", flags=_re.DOTALL)
            data = _json.loads(m.group(0)) if m else {}
            dec = (data.get("decision") or "ADD").upper()
            if dec not in ("MERGE", "ADD"):
                dec = "ADD"
            tgt = data.get("target")
            if dec == "MERGE" and tgt not in {nb["id"] for nb in neighbours}:
                dec, tgt = "ADD", None
            return {"decision": dec, "target": tgt, "reason": data.get("reason", "")}
        except Exception as e:  # noqa: BLE001
            return {"decision": "ADD", "target": None, "reason": f"LLM error fallback: {e}"}


def judge_terms(new_terms: list[dict], neighbours_map: dict[str, list[dict]], judge: MergeJudge) -> dict[str, dict]:
    decisions: dict[str, dict] = {}
    for t in new_terms:
        can = t["canonical"]
        neigh = neighbours_map.get(can, [])
        # delegate to MergeJudge.judge
        res = judge.judge(can, t.get("type", "concept"), neigh)
        decisions[can] = res
    return decisions


def judge_relations(new_rels: list[Relation], neighbours_map: dict[tuple, list[dict]], judge: RelMergeJudge) -> dict[tuple, dict]:
    decisions: dict[tuple, dict] = {}
    for r in new_rels:
        key = (r.source, r.rel, r.target)
        neigh = neighbours_map.get(key, [])
        res = judge.judge(r, neigh)
        decisions[key] = res
    return decisions

# ---------------------------------------------------------------------------
# Step 4 — update
# ---------------------------------------------------------------------------

def apply_term_decisions(new_terms: list[dict], decisions: dict[str, dict],
                         dictionary: Dictionary, onto: Ontology,
                         term_index: EmbeddingIndex) -> tuple[Dictionary, Ontology, dict]:
    existing_can_lower = {c.canonical.lower() for c in onto.concepts}
    existing_surfaces_lower = {e.surface.lower() for e in dictionary.entries.values()}
    id_by_lower = {c.canonical.lower(): c.id for c in onto.concepts}
    by_id = {c.id: c for c in onto.concepts}
    new_entries = dict(dictionary.entries)
    new_concepts = {c.id: c for c in onto.concepts}
    summary = {"terms_added": 0, "terms_merged": 0, "aliases_added": 0}
    for t in new_terms:
        can = t["canonical"].strip()
        if not can:
            continue
        dec = decisions.get(can, {"decision": "ADD"})
        if dec.get("decision") == "MERGE" and dec.get("target"):
            tgt = dec["target"]
            target = by_id.get(tgt) or new_concepts.get(tgt)
            if target is not None:
                # merge canonical as alias of target
                if can != target.canonical and can not in target.aliases:
                    target.aliases.append(can)
                    summary["aliases_added"] += 1
                summary["terms_merged"] += 1
                continue
        # ADD path: skip if canonical lower already exists (race after term decisions within same chunk)
        if can.lower() in existing_can_lower or can.lower() in {c.canonical.lower() for c in new_concepts.values() if c.canonical.lower() != can.lower()}:
            # check if decision said ADD but concept already present means duplicate; count as merged
            _existing = id_by_lower.get(can.lower())
            if _existing and _existing in by_id:
                summary["terms_merged"] += 1
            continue
        # add to dict+onto+index
        ctype = t.get("type", "concept")
        if can.lower() not in existing_surfaces_lower:
            new_entries[can] = DictionaryEntry(surface=can, canonical=can, type=ctype, aliases=[])
        cid = can.lower().replace(" ", "_")
        if cid not in new_concepts:
            new_concepts[cid] = Concept(id=cid, canonical=can, type=ctype, aliases=[])
            summary["terms_added"] += 1
            try:
                term_index.add(cid, can)
            except Exception:
                pass
            existing_can_lower.add(can.lower())
            id_by_lower[can.lower()] = cid
            by_id[cid] = new_concepts[cid]
    # rebuild dict automaton, ontology
    new_dict = build_automaton(new_entries)
    new_onto = Ontology(concepts=list(new_concepts.values()), relations=list(onto.relations))
    return new_dict, new_onto, summary


def apply_relation_decisions(new_rels: list[Relation], decisions: dict[tuple, dict],
                             onto: Ontology, rel_index: EmbeddingIndex) -> tuple[Ontology, dict]:
    existing = {(r.source, r.rel, r.target) for r in onto.relations}
    rels = list(onto.relations)
    summary = {"relations_added": 0, "relations_merged": 0}
    for r in new_rels:
        key = (r.source, r.rel, r.target)
        dec = decisions.get(key, {"decision": "ADD"})
        if dec.get("decision") == "MERGE":
            summary["relations_merged"] += 1
            continue
        if key in existing:
            summary["relations_merged"] += 1
            continue
        # ADD
        rels.append(r)
        existing.add(key)
        summary["relations_added"] += 1
        # keep rel index in sync
        rid = f"{r.source}|{r.rel}|{r.target}"
        try:
            rel_index.add(rid, f"{r.source} {r.rel} {r.target}")
        except Exception:
            pass
    new_onto = Ontology(concepts=list(onto.concepts), relations=rels)
    return new_onto, summary

# ---------------------------------------------------------------------------
# Per-chunk v2
# ---------------------------------------------------------------------------

def step1_terms_queued(section: Section, onto: Ontology, extract_queue, max_chars: int = 800) -> tuple[list, dict]:
    """Queued variant of step1_terms — AI via ModelQueue when available."""
    cand = extract_candidates([section])
    det_map: dict[str, dict] = {}
    for c in cand:
        key = c.canonical.strip().lower()
        if not key:
            continue
        det_map[key] = {"canonical": c.canonical.strip(), "type": c.type, "confidence": c.confidence, "aliases": list(c.aliases)}
    retries: list[int] = []
    ai_list = ai_extract_terms_queued(section, extract_queue, max_chars=max_chars, retries=retries)
    for t in ai_list:
        can = (t.get("canonical") or "").strip()
        if not can:
            continue
        key = can.lower()
        ctype = t.get("type") or "concept"
        conf = float(t.get("confidence", 0.5) or 0.5)
        if key not in det_map or conf > det_map[key].get("confidence", 0):
            det_map[key] = {"canonical": can, "type": ctype, "confidence": conf, "aliases": []}
    new_terms = list(det_map.values())
    meta = {"det": len(cand), "ai": len(ai_list), "union": len(new_terms), "retries": retries[0] if retries else 0}
    return new_terms, meta


def step1_relations_queued(section: Section, onto: Ontology, relations_queue, max_chars: int = 800) -> tuple[list[Relation], dict]:
    """Queued variant of step1_relations — AI via ModelQueue."""
    cand_rels = extract_relations([section], onto)
    known_rels = [r for r in onto.relations if r.source in {c.id for c in onto.concepts}][:20]
    retries: list[int] = []
    ai_list = ai_extract_relations_queued(section, known_rels, cand_rels, relations_queue, max_chars=max_chars, retries=retries)
    concept_ids = {c.id for c in onto.concepts}
    id_by_canonical = {c.canonical.lower(): c.id for c in onto.concepts}
    ai_rels: list[Relation] = []
    for r in ai_list:
        src = (r.get("source") or "").strip()
        tgt = (r.get("target") or "").strip()
        rel = (r.get("rel") or "").strip()
        if not src or not tgt or not rel:
            continue
        sid = src.lower().replace(" ", "_")
        tid = tgt.lower().replace(" ", "_")
        if sid not in concept_ids:
            sid = id_by_canonical.get(src.lower()) or sid
        if tid not in concept_ids:
            tid = id_by_canonical.get(tgt.lower()) or tid
        if sid not in concept_ids or tid not in concept_ids:
            continue
        ai_rels.append(Relation(source=sid, rel=rel, target=tid, confidence=float(r.get("confidence", 0.8) or 0.8)))
    seen: dict[tuple[str,str,str], Relation] = {}
    for r in cand_rels:
        seen[(r.source, r.rel, r.target)] = r
    for r in ai_rels:
        key = (r.source, r.rel, r.target)
        if key not in seen or r.confidence > seen[key].confidence:
            seen[key] = r
    new_relations = list(seen.values())
    meta = {"det": len(cand_rels), "ai": len(ai_rels), "union": len(new_relations), "retries": retries[0] if retries else 0}
    return new_relations, meta


def process_chunk_v2(section: Section, dictionary: Dictionary, onto: Ontology,
                     term_index: EmbeddingIndex, rel_index: EmbeddingIndex,
                     extract_client: LLMClient | None, relations_client: LLMClient | None,
                     merge_judge: MergeJudge, rel_judge: RelMergeJudge,
                     max_chars: int = 800, threshold: float = 0.25, top_k: int = 5) -> tuple[Dictionary, Ontology, dict]:
    meta: dict = {"clause": section.clause}
    # -- TERMS: step1-3 --
    new_terms, m1 = step1_terms(section, onto, extract_client, max_chars=max_chars)
    meta["terms_step1"] = m1
    term_neigh = neighbours_for_terms(new_terms, onto, term_index, threshold=threshold, top_k=top_k, dictionary=dictionary)
    meta["terms_step2_avg_neighbours"] = round(sum(len(v) for v in term_neigh.values()) / max(1, len(term_neigh)), 2) if term_neigh else 0
    term_decs = judge_terms(new_terms, term_neigh, merge_judge)
    meta["terms_step3_add"] = sum(1 for d in term_decs.values() if d.get("decision") == "ADD")
    meta["terms_step3_merge"] = sum(1 for d in term_decs.values() if d.get("decision") == "MERGE")
    dictionary, onto, sum_terms = apply_term_decisions(new_terms, term_decs, dictionary, onto, term_index)
    meta.update(sum_terms)

    # -- RELATIONS: step1-3 (uses updated onto so AI relations can resolve new term ids) --
    new_rels, m1r = step1_relations(section, onto, relations_client, max_chars=max_chars)
    meta["rels_step1"] = m1r
    rel_neigh = neighbours_for_relations(new_rels, rel_index, threshold=threshold, top_k=top_k)
    meta["rels_step2_avg_neighbours"] = round(sum(len(v) for v in rel_neigh.values()) / max(1, len(rel_neigh)), 2) if rel_neigh else 0
    rel_decs = judge_relations(new_rels, rel_neigh, rel_judge)
    meta["rels_step3_add"] = sum(1 for d in rel_decs.values() if d.get("decision") == "ADD")
    meta["rels_step3_merge"] = sum(1 for d in rel_decs.values() if d.get("decision") == "MERGE")
    onto, sum_rels = apply_relation_decisions(new_rels, rel_decs, onto, rel_index)
    meta.update(sum_rels)
    return dictionary, onto, meta


def process_chunk_v2_parallel(section: Section, dictionary: Dictionary, onto: Ontology,
                              term_index: EmbeddingIndex, rel_index: EmbeddingIndex,
                              queues: dict | None, merge_judge: MergeJudge, rel_judge: RelMergeJudge,
                              max_chars: int = 800, threshold: float = 0.25, top_k: int = 5) -> tuple[Dictionary, Ontology, dict]:
    """Parallel variant: term extract + merge judge via ModelQueue, relations likewise."""
    ex_q = queues.get("extract") if queues else None
    rel_q = queues.get("relations") if queues else None
    merge_q = queues.get("merge") if queues else None
    meta: dict = {"clause": section.clause, "parallel": True}
    # -- TERMS --
    new_terms, m1 = step1_terms_queued(section, onto, ex_q, max_chars=max_chars)
    meta["terms_step1"] = m1
    term_neigh = neighbours_for_terms(new_terms, onto, term_index, threshold=threshold, top_k=top_k, dictionary=dictionary)
    meta["terms_step2_avg_neighbours"] = round(sum(len(v) for v in term_neigh.values()) / max(1, len(term_neigh)), 2) if term_neigh else 0
    term_decs = judge_terms_parallel(new_terms, term_neigh, merge_judge, merge_q)
    meta["terms_step3_add"] = sum(1 for d in term_decs.values() if d.get("decision") == "ADD")
    meta["terms_step3_merge"] = sum(1 for d in term_decs.values() if d.get("decision") == "MERGE")
    dictionary, onto, sum_terms = apply_term_decisions(new_terms, term_decs, dictionary, onto, term_index)
    meta.update(sum_terms)
    # -- RELATIONS (uses updated onto) --
    new_rels, m1r = step1_relations_queued(section, onto, rel_q, max_chars=max_chars)
    meta["rels_step1"] = m1r
    rel_neigh = neighbours_for_relations(new_rels, rel_index, threshold=threshold, top_k=top_k)
    meta["rels_step2_avg_neighbours"] = round(sum(len(v) for v in rel_neigh.values()) / max(1, len(rel_neigh)), 2) if rel_neigh else 0
    rel_decs = judge_relations(new_rels, rel_neigh, rel_judge)
    meta["rels_step3_add"] = sum(1 for d in rel_decs.values() if d.get("decision") == "ADD")
    meta["rels_step3_merge"] = sum(1 for d in rel_decs.values() if d.get("decision") == "MERGE")
    onto, sum_rels = apply_relation_decisions(new_rels, rel_decs, onto, rel_index)
    meta.update(sum_rels)
    return dictionary, onto, meta

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_queues(app):
    """Build one ModelQueue per LLM task (extract/relations/merge). Returns dict or None."""
    if ModelQueue is None or not getattr(app.llm, "enabled", False):
        return None
    qs: dict = {}
    for task in ("extract", "relations", "merge"):
        try:
            cfg = app.llm.models.get(task, app.llm.default) if app.llm.models else app.llm.default
            qs[task] = ModelQueue(key=task, config=cfg, maxsize=16)
        except Exception:
            continue
    return qs or None


def ai_extract_terms_queued(section: Section, queue, max_chars: int = 800,
                            retries: list | None = None) -> list[dict]:
    """Queue-backed extract; falls back to sync when queue is None."""
    if queue is None:
        # Use disabled client fallback path via sync helper with None
        from onto3gpp.llm import LLMClient as _LC
        return ai_extract_terms(section, None, max_chars=max_chars, retries=retries)  # type: ignore
    prompt = EXTRACT_PROMPT_TEMPLATE.format(text=section.text[:max_chars], types=CONCEPT_TYPES)
    try:
        data = queue.submit_json(prompt, max_tokens=queue.config.max_tokens,  # type: ignore
                                 temperature=queue.config.temperature, attempts=5, retries=retries).result(timeout=90)
        return data.get("concepts", []) if isinstance(data, dict) else []
    except Exception:
        return []


def ai_extract_relations_queued(section: Section, known_rels, candidate_rels, queue, max_chars: int = 800,
                                retries: list | None = None) -> list[dict]:
    if queue is None:
        return ai_extract_relations(section, known_rels, candidate_rels, None, max_chars=max_chars, retries=retries)  # type: ignore
    prompt = RELATIONS_PROMPT_TEMPLATE.format(
        text=section.text[:max_chars],
        known_relations=_fmt_relations(known_rels),
        candidate_relations=_fmt_relations(candidate_rels),
    )
    try:
        data = queue.submit_json(prompt, max_tokens=queue.config.max_tokens,  # type: ignore
                                 temperature=queue.config.temperature, attempts=5, retries=retries).result(timeout=90)
        return data.get("relations", []) if isinstance(data, dict) else []
    except Exception:
        return []


def judge_terms_parallel(new_terms: list[dict], neighbours_map: dict[str, list[dict]],
                         judge: MergeJudge, merge_queue=None) -> dict[str, dict]:
    """Parallel LLM judge via ModelQueue when available; else sequential fallback."""
    if merge_queue is None or not getattr(merge_queue.config, "enabled", False):
        return judge_terms(new_terms, neighbours_map, judge)
    # submit all that need LLM in parallel
    futures: dict[str, object] = {}
    results: dict[str, dict] = {}
    for t in new_terms:
        can = t["canonical"]
        neigh = neighbours_map.get(can, [])
        # deterministic fast-path without LLM (no neighbours or exact match) — avoid queue
        if not neigh:
            results[can] = {"decision": "ADD", "target": None, "reason": "no neighbours"}
            continue
        # If judge would take deterministic path (LLM disabled fallback) we already handled enabled case;
        # but still check normalized fast-path to avoid LLM call when obvious merge
        from onto3gpp.ingest.merge_judge import _normalize as _norm, _compact as _cmp, _denied as _den
        norm_new = _norm(can)
        cmp_new = _cmp(can)
        lid_new = can.lower().replace(" ", "_").replace("-", "_")
        decided = None
        for nb in neigh:
            if _den(can, nb["canonical"]):
                continue
            if _norm(nb["canonical"]) == norm_new or _cmp(nb["canonical"]) == cmp_new or nb["canonical"].lower().replace(" ", "_").replace("-", "_") == lid_new:
                decided = {"decision": "MERGE", "target": nb["id"], "reason": f"normalized match: {nb['canonical']!r}"}
                break
        if decided is not None:
            results[can] = decided
            continue
        # Need LLM — craft prompt matching MergeJudge
        nb_lines = "\n".join(
            f'- id={nb["id"]!r} canonical={nb["canonical"]!r} type={nb["type"]!r} cosine={nb["cosine"]:.3f}'
            for nb in neigh
        )
        prompt = (
            "You are a 3GPP ontology merge judge. Decide if a newly extracted term "
            "is the SAME concept as one of the existing neighbours (MERGE) or a "
            "distinct concept (ADD). Be conservative: timers, DCI formats, and "
            "identifiers that differ by a single character (e.g. T3444 vs T3445, "
            "C1-174182 vs C1-174183, ACTIVE vs INACTIVE, DCI-1-0 vs DCI-0-1) are "
            "DISTINCT. Hyphen/space/case variants (NGAP vs NG-AP, E-UTRAN vs EUTRAN) "
            "ARE the same.\n\n"
            f"New term: canonical={can!r} type={t.get('type','concept')!r}\n"
            f"Neighbours:\n{nb_lines}\n\n"
            'Reply with JSON only: {"decision": "MERGE"|"ADD", "target": "<id or null>", "reason": "..."}'
        )
        try:
            fut = merge_queue.submit_json(prompt, attempts=3)
            futures[can] = fut
        except Exception:
            results[can] = judge.judge(can, t.get("type", "concept"), neigh)
    for can, fut in futures.items():
        try:
            data = fut.result(timeout=90)  # type: ignore
            dec = (data.get("decision") or "ADD").upper() if isinstance(data, dict) else "ADD"
            if dec not in ("MERGE", "ADD"):
                dec = "ADD"
            tgt = data.get("target") if isinstance(data, dict) else None
            neigh_ids = {nb["id"] for nb in neighbours_map.get(can, [])}
            if dec == "MERGE" and tgt not in neigh_ids:
                dec, tgt = "ADD", None
            results[can] = {"decision": dec, "target": tgt, "reason": data.get("reason", "") if isinstance(data, dict) else ""}
        except Exception as e:  # noqa: BLE001
            # fallback to sequential judge
            neigh = neighbours_map.get(can, [])
            try:
                results[can] = judge.judge(can, next((x for x in new_terms if x["canonical"] == can), {}).get("type", "concept"), neigh)
            except Exception:
                results[can] = {"decision": "ADD", "target": None, "reason": f"queue error fallback: {e}"}
    return results


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="AI Ingest v2 per-chunk extract→match→merge (terms+relations)")
    ap.add_argument("--parsed", required=True, help="Parsed JSONL (sections)")
    ap.add_argument("--base-dict", required=True, help="Bootstrap dict.json")
    ap.add_argument("--base-ontology", required=True, help="Bootstrap ontology.json")
    ap.add_argument("--dict", required=True, help="Output dict.json (checkpoint)")
    ap.add_argument("--ontology", required=True, help="Output ontology.json (checkpoint)")
    ap.add_argument("--app-config", default=None, help="App config YAML (providers+llm+embed)")
    ap.add_argument("--max-chars", type=int, default=800)
    ap.add_argument("--threshold", type=float, default=None, help="Embedding threshold override")
    ap.add_argument("--top-k", type=int, default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--empty", action="store_true", help="Bootstrap from empty dict/ontology")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--parallel", type=int, default=0, help="Parallel LLM queue size (0=sequential, >0 enables ModelQueue for extract/relations/merge)")
    return ap


def main() -> None:
    args = build_parser().parse_args()
    app = load_app_config(Path(args.app_config) if args.app_config else None)
    parallel = int(getattr(args, "parallel", 0) or 0)
    queues = _build_queues(app) if parallel else None
    if queues:
        print(f"parallel: queues={list(queues.keys())} (maxsize=16 each)")
    # Task routing for extract/relations/merge judges (also used for sequential fallback)
    def _client_for(task: str) -> LLMClient | None:
        try:
            cfg = app.llm.models.get(task, app.llm.default) if app.llm.models else app.llm.default
            return LLMClient(cfg)
        except Exception:
            return None
    extract_client = _client_for("extract")
    relations_client = _client_for("relations")
    merge_client = _client_for("merge")
    merge_judge = MergeJudge(llm_client=merge_client)
    rel_judge = RelMergeJudge(llm_client=merge_client)

    # Embed factory from app.embed
    embed_cfg = {
        "kind": getattr(app.embed, "kind", "hash"),
        "dim": getattr(app.embed, "dim", 384),
        "threshold": getattr(app.embed, "threshold", 0.25),
        "top_k": getattr(app.embed, "top_k", 5),
    }
    # Optional overrides
    for k in ("api_base", "model", "api_key", "api_key_env"):
        v = getattr(app.embed, k, None)
        if v is not None:
            embed_cfg[k] = v
    threshold = args.threshold if args.threshold is not None else float(embed_cfg.get("threshold", 0.25))
    top_k = args.top_k if args.top_k is not None else int(embed_cfg.get("top_k", 5))
    embedder = get_embedder(embed_cfg)
    print(f"app: providers={list(app.providers.keys())} llm.enabled={app.llm.enabled} embed={embed_cfg} threshold={threshold} top_k={top_k}")
    if app.llm.enabled:
        print(f" routing: extract={extract_client.config.model if extract_client else '?'} "
              f"relations={relations_client.config.model if relations_client else '?'} "
              f"merge={merge_client.config.model if merge_client else '?'} (judge llm={'on' if merge_judge._llm_available else 'fallback'})")
    else:
        print(" routing: LLM disabled — judges in deterministic fallback (no false merges)")

    dict_path = Path(args.dict)
    onto_path = Path(args.ontology)
    # Bootstrap
    if args.resume:
        if not (dict_path.exists() and onto_path.exists()):
            raise SystemExit(f"Resume requested but checkpoint missing: {dict_path} / {onto_path}")
        dictionary = load_dict(dict_path)
        onto = load_ontology(onto_path)
        print(f"Resumed: {len(dictionary.entries)} dict, {len(onto.concepts)} concepts, {len(onto.relations)} relations")
    elif args.empty:
        dictionary = build_automaton({})
        onto = Ontology()
        print(f"Bootstrap (EMPTY): {len(dictionary.entries)} dict, {len(onto.concepts)} concepts")
    else:
        dictionary = load_dict(Path(args.base_dict))
        onto = load_ontology(Path(args.base_ontology))
        print(f"Bootstrap: {len(dictionary.entries)} dict, {len(onto.concepts)} concepts, {len(onto.relations)} relations")

    sections = load_sections(Path(args.parsed))
    if args.limit:
        sections = sections[: args.limit]
    total = len(sections)
    # Resume tracking by index
    done: set[int] = set()
    log_path = dict_path.with_suffix(".progress.jsonl")
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                idx = rec.get("index")
                if idx is None:
                    idx = rec.get("clause")
                if idx is not None and isinstance(idx, int):
                    done.add(idx)
    # Indexes (incremental)
    term_index = build_term_index(onto, embedder)
    rel_index = build_rel_index(onto, embedder)
    print(f"Indexes: term {len(term_index.ids)} concepts, rel {len(rel_index.ids)} relations (dim={embedder.dim})")

    ok = fail = 0
    t_start = time.time()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for i, section in enumerate(sections):
            if i in done:
                continue
            try:
                if queues is not None:
                    dictionary, onto, meta = process_chunk_v2_parallel(
                        section, dictionary, onto, term_index, rel_index, queues,
                        merge_judge, rel_judge,
                        max_chars=args.max_chars, threshold=threshold, top_k=top_k,
                    )
                else:
                    dictionary, onto, meta = process_chunk_v2(
                        section, dictionary, onto, term_index, rel_index,
                        extract_client, relations_client, merge_judge, rel_judge,
                        max_chars=args.max_chars, threshold=threshold, top_k=top_k,
                    )
                ok += 1
                save_dict(dictionary, dict_path)
                save_ontology(onto, onto_path)
                log.write(json.dumps({"index": i, "clause": section.clause, "meta": meta}) + "\n")
                log.flush()
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.write(json.dumps({"index": i, "clause": section.clause, "error": str(e)}) + "\n")
                log.flush()
            if (i + 1) % 10 == 0 or i == total - 1:
                el = time.time() - t_start
                rate = (ok + fail) / el if el else 0
                print(f"[{i+1}/{total}] ok={ok} fail={fail} rate={rate:.2f}/s "
                      f"dict={len(dictionary.entries)} concepts={len(onto.concepts)} rels={len(onto.relations)} "
                      f"term_idx={len(term_index.ids)} rel_idx={len(rel_index.ids)} elapsed={el:.0f}s",
                      flush=True)
            if args.sleep:
                time.sleep(args.sleep)
    if queues is not None:
        for q in queues.values():
            try:
                q.shutdown()
            except Exception:
                pass

    errors = validate_ontology(onto)
    if errors:
        print(f"Validation errors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  - {e}")
    print(f"DONE: ok={ok} fail={fail} final_dict={len(dictionary.entries)} "
          f"final_concepts={len(onto.concepts)} final_relations={len(onto.relations)} "
          f"total_time={time.time()-t_start:.0f}s")


if __name__ == "__main__":
    main()
