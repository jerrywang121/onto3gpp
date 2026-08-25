"""Progressive AI-assisted extraction (prototype).

A different strategy from `ai_extract.py` (which asked the AI to extract
concepts from scratch and produced generic, non-discriminative terms that
REGRESSED retrieval). This method is **progressive and context-aware**:

For each input chunk (section):
  a) Deterministic extraction -> candidate terms + relations
     (`extract_candidates`, `extract_relations`).
  b) Match the chunk against the CURRENT dict + ontology to find known terms
     and their relations.
  c) Give the AI model the chunk + the outputs of (a) and (b), and ask it
     which terms/relations to ADD or UPDATE (i.e. fill gaps the deterministic
     extractor missed, not re-extract everything).
  d) Apply the AI's additions/updates to the dict + ontology graph, then
     continue to the next chunk.

The dict + ontology are updated incrementally, so later chunks see the
accumulated knowledge (progressive bootstrapping).

Checkpointed + resumable: the running dict/ontology are written to disk after
each chunk, so a partial run can be resumed without redoing work.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from ai_helpers import complete_json  # noqa: E402

from onto3gpp.compile.dictionary import Dictionary, DictionaryEntry, build_automaton  # noqa: E402
from onto3gpp.config import load_domain  # noqa: E402
from onto3gpp.extract.relations import extract_relations  # noqa: E402
from onto3gpp.extract.terms import extract_candidates  # noqa: E402
from onto3gpp.llm import LLMConfig  # noqa: E402
from onto3gpp.ontology.schema import (  # noqa: E402
    Concept,
    Ontology,
    Relation,
    ontology_from_dict,
    ontology_to_dict,
    validate_ontology,
)
from onto3gpp.parser import Section  # noqa: E402

CONCEPT_TYPES = (
    "network_function, procedure, information_element, interface, protocol, "
    "qos, architecture, security"
)

# The flaky local model fails to produce verdicts when the candidate list is
# too long. Cap how many candidates are shown to the verify prompt; candidates
# beyond the cap (and any without a verdict) are kept deterministically.
VERIFY_CANDIDATE_CAP = 10

# NOTE: the local ollama models are flaky and return EMPTY when given an
# exclusion list ("do NOT re-add these") or when asked to produce several
# distinct JSON fields in one prompt. The reliable format is a plain "extract
# concepts" prompt. So we split the work into THREE separate LLM calls per
# chunk, each best-effort with a deterministic fallback:
#
#   1) EXTRACT_PROMPT_TEMPLATE (reliable): identify NEW concepts. Already-known
#      concepts are filtered out deterministically in apply_result.
#   2) VERIFY_PROMPT_TEMPLATE (best-effort): judge each deterministic candidate
#      (Q2). If it fails, candidates are kept deterministically.
#   3) RELATIONS_PROMPT_TEMPLATE (best-effort): propose relations to add/update
#      (Q3). If it fails, relations are re-extracted deterministically.
#
# This satisfies the user's design requirements (verify deterministic output,
# feed relation info) while keeping the reliable extract path intact.
EXTRACT_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the specification text below, identify NEW technical concepts (terms) that are NOT already covered by the existing knowledge base.

The existing knowledge base already contains these terms:
{known}

Text:
{text}

List each NEW concept with its type (choose from: {types}) and a confidence 0-1. Return ONLY a JSON object of the form:
{{"concepts": [{{"canonical": "term", "type": "type", "confidence": 0.9}}]}}"""

VERIFY_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Judge whether each deterministic candidate term below is a real, discriminative 3GPP concept worth adding to the ontology.

The deterministic extractor found these candidate terms (each has an id):
{candidates}

Text:
{text}

For EACH candidate id, return keep true or false. Return ONLY a JSON object of the form:
{{"verdicts": [{{"id": 0, "keep": true, "type": "interface", "confidence": 0.9}}]}}"""

RELATIONS_PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the text below, propose relations between technical concepts to add or update.

The existing knowledge base already contains these relations:
{known_relations}

The deterministic extractor found these candidate relations:
{candidate_relations}

Text:
{text}

Return ONLY a JSON object of the form:
{{"relations": [{{"source": "term", "rel": "uses", "target": "term", "confidence": 0.9}}]}}

Use relation types like: uses, connects, carries, handles, establishes, forwards, selects, maps, applies, initiates, moves, updates, is_a. Only include relations you are confident about."""


def load_sections(parsed: Path) -> list[Section]:
    sections: list[Section] = []
    for line in parsed.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        sections.append(
            Section(
                spec=data["spec"],
                release=data["release"],
                clause=data["clause"],
                title=data["title"],
                text=data["text"],
                parent_clause=data.get("parent_clause", ""),
                metadata=data.get("metadata", {}),
            )
        )
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


def _fmt_candidates(candidates, cap: int = 0) -> str:
    """Format candidates with ids for the prompt. `cap` limits how many are
    shown (the flaky model fails on very long candidate lists); 0 = no cap."""
    if not candidates:
        return "(none)"
    shown = candidates if cap <= 0 else candidates[:cap]
    return "\n".join(
        f"- [{i}] {c.canonical} [{c.type}]" for i, c in enumerate(shown)
    )


def _fmt_known(known: list[str]) -> str:
    if not known:
        return "(none)"
    return "\n".join(f"- {k}" for k in known)


def _fmt_relations(relations) -> str:
    if not relations:
        return "(none)"
    return "\n".join(
        f"- {r.source} --{r.rel}--> {r.target}" for r in relations
    )


def compute_snapshot(section, d, onto, max_chars=800) -> dict:
    """Compute the per-chunk inputs shared by all three pipeline stages."""
    candidates = extract_candidates([section])
    known = d.find(section.text)
    known_rels = [r for r in onto.relations
                  if r.source in known or r.target in known]
    candidate_rels = extract_relations([section], onto)
    return {
        "candidates": candidates,
        "known": known,
        "known_rels": known_rels,
        "candidate_rels": candidate_rels,
        "text": section.text[:max_chars],
    }


def stage_extract(section, snapshot, model, configs) -> tuple:
    """Stage 1: AI extracts NEW concepts. Returns (result, fallback, retries)."""
    retries: list = []
    prompt = EXTRACT_PROMPT_TEMPLATE.format(
        text=snapshot["text"], types=CONCEPT_TYPES,
        known=_fmt_known(snapshot["known"]),
    )
    try:
        result = complete_json(prompt, model, max_tokens=2048, attempts=10,
                               config=configs.get("extract"), retries=retries)
        return result, False, retries
    except Exception:  # noqa: BLE001
        return {}, True, retries


def stage_verify(section, snapshot, model, configs) -> dict:
    """Run the verify stage (Q2). Returns (result, fallback, retries)."""
    retries: list = []
    candidates = snapshot["candidates"]
    if not candidates:
        return {}, False, retries
    prompt = VERIFY_PROMPT_TEMPLATE.format(
        text=snapshot["text"],
        candidates=_fmt_candidates(candidates, cap=VERIFY_CANDIDATE_CAP),
    )
    try:
        result = complete_json(prompt, model, max_tokens=2048, attempts=5,
                               config=configs.get("verify"), retries=retries)
        return result, False, retries
    except Exception:  # noqa: BLE001
        return {}, True, retries


def stage_relations(section, snapshot, model, configs) -> dict:
    """Run the relations stage (Q3). Returns (result, fallback, retries)."""
    retries: list = []
    prompt = RELATIONS_PROMPT_TEMPLATE.format(
        text=snapshot["text"],
        known_relations=_fmt_relations(snapshot["known_rels"]),
        candidate_relations=_fmt_relations(snapshot["candidate_rels"]),
    )
    try:
        result = complete_json(prompt, model, max_tokens=2048, attempts=5,
                               config=configs.get("relations"), retries=retries)
        return result, False, retries
    except Exception:  # noqa: BLE001
        return {}, True, retries


def process_chunk(
    section: Section,
    d: Dictionary,
    onto: Ontology,
    model: str,
    max_chars: int = 800,
    configs: dict[str, LLMConfig] | None = None,
) -> dict:
    """Run the a/b/c/d progressive step for one chunk. Returns the AI result.

    (a) deterministic extraction -> candidate terms (used for context)
    (b) known terms in this chunk (from the current dict)
    (c) AI extracts concepts from the chunk (reliable format); already-known
        concepts are filtered out deterministically in apply_result.

    ``model`` is the fallback model name; ``configs`` (optional) maps task
    name -> LLMConfig for per-task routing (extract/verify/relations). When a
    task has a config, it overrides ``model`` and the hard-coded max_tokens.

    The returned dict includes `_match` metadata: the number of known terms
    matched in this chunk (from the current dict) and the number of known
    relations matched (from the current ontology). These grow as the dict and
    ontology expand, so we monitor them to detect context/performance growth.
    """
    configs = configs or {}
    snapshot = compute_snapshot(section, d, onto, max_chars)
    fallback = {"extract": False, "verify": False, "relations": False}
    retries = {"extract": [], "verify": [], "relations": []}

    result, fallback["extract"], retries["extract"] = stage_extract(
        section, snapshot, model, configs)
    verify_result, fallback["verify"], retries["verify"] = stage_verify(
        section, snapshot, model, configs)
    relations_result, fallback["relations"], retries["relations"] = \
        stage_relations(section, snapshot, model, configs)

    result["_verify"] = verify_result
    result["_relations"] = relations_result
    result["_fallback"] = fallback
    result["_retries"] = {k: v[0] if v else 0 for k, v in retries.items()}
    result["_match"] = {
        "known_terms": len(snapshot["known"]),
        "known_relations": len(snapshot["known_rels"]),
        "candidates": len(snapshot["candidates"]),
    }
    result["_candidates"] = snapshot["candidates"]
    return result


def apply_result(
    result: dict,
    dictionary: Dictionary,
    onto: Ontology,
    section: Section,
    candidates=None,
) -> tuple[Dictionary, Ontology, dict]:
    """Apply the AI's decisions to the dict + ontology.

    Three kinds of AI output are applied:
      - "concepts": NEW concepts to add (deterministic "AI fills gaps" filter
        skips anything already known).
      - "candidate_verdicts": for each deterministic candidate, whether to
        keep it (Q2: AI verifies the deterministic extractor's output).
      - "relations": relations to add/update between known concepts (Q3).

    Returns (new_dict, new_ontology, summary).
    """
    summary = {
        "terms_added": 0,
        "relations_added": 0,
        "terms_updated": 0,
        "candidates_kept": 0,
        "candidates_dropped": 0,
    }

    # --- add terms (only NEW ones) ---
    existing_surfaces = {e.surface.lower() for e in dictionary.entries.values()}
    existing_ids = {c.id for c in onto.concepts}
    existing_canonical_lower = {c.canonical.lower() for c in onto.concepts}

    new_entries: dict[str, DictionaryEntry] = dict(dictionary.entries)
    new_concepts: dict[str, Concept] = {c.id: c for c in onto.concepts}

    def _add_concept(canonical: str, ctype: str) -> None:
        nonlocal summary
        canonical = canonical.strip()
        if not canonical:
            return
        if canonical.lower() in existing_canonical_lower:
            return  # already known — skip (AI fills gaps only)
        # add to dict
        if canonical.lower() not in existing_surfaces:
            new_entries[canonical] = DictionaryEntry(
                surface=canonical, canonical=canonical, type=ctype, aliases=[]
            )
            summary["terms_added"] += 1
        # add to ontology
        cid = canonical.lower().replace(" ", "_")
        if cid not in existing_ids:
            new_concepts[cid] = Concept(id=cid, canonical=canonical, type=ctype)
            summary["terms_added"] += 1

    # 1) NEW concepts from the AI
    for t in result.get("concepts", []):
        canonical = (t.get("canonical") or "").strip()
        if not canonical:
            continue
        ctype = t.get("type", "concept")
        _add_concept(canonical, ctype)

    # 2) candidate verdicts (Q2): keep the deterministic candidates the AI
    #    judged worth adding. `candidates` is the same list the prompt saw.
    #    Only candidates explicitly marked keep:false are dropped; everything
    #    else (no verdict, or beyond the cap) is kept deterministically so a
    #    flaky verdict call never loses concepts.
    verify = result.get("_verify", {})
    if candidates:
        verdicts = verify.get("verdicts", [])
        dropped: set[int] = set()
        for v in verdicts:
            idx = v.get("id")
            if idx is None or not (0 <= idx < len(candidates)):
                continue
            if v.get("keep"):
                _add_concept(candidates[idx].canonical, v.get("type") or candidates[idx].type)
                summary["candidates_kept"] += 1
            else:
                dropped.add(idx)
                summary["candidates_dropped"] += 1
        # keep any candidate that did not get an explicit keep:false verdict
        for idx, cand in enumerate(candidates):
            if idx not in dropped:
                _add_concept(cand.canonical, cand.type)
                summary["candidates_kept"] += 1

    # --- relations ---
    # Preserve previously accumulated relations, add this chunk's new ones.
    new_onto = Ontology(concepts=list(new_concepts.values()))
    existing_rels = {(r.source, r.rel, r.target) for r in onto.relations}
    new_relations = list(onto.relations)

    def add_relation(source: str, rel: str, target: str) -> None:
        nonlocal new_relations, existing_rels
        if (source, rel, target) in existing_rels:
            return
        new_relations.append(Relation(source=source, rel=rel, target=target))
        existing_rels.add((source, rel, target))
        summary["relations_added"] += 1

    # 3) AI-proposed relations (Q3): only keep those whose endpoints are known
    #    concepts in the ontology (deterministic safety net).
    concept_ids = {c.id for c in new_concepts.values()}
    for r in result.get("_relations", {}).get("relations", []):
        source = (r.get("source") or "").strip()
        target = (r.get("target") or "").strip()
        rel = (r.get("rel") or "").strip()
        if not source or not target or not rel:
            continue
        sid = source.lower().replace(" ", "_")
        tid = target.lower().replace(" ", "_")
        if sid not in concept_ids or tid not in concept_ids:
            continue
        add_relation(sid, rel, tid)

    # 4) deterministic re-extraction over the updated ontology (reliable path)
    chunk_relations = extract_relations([section], new_onto)
    for r in chunk_relations:
        add_relation(r.source, r.rel, r.target)

    new_onto.relations = new_relations

    # rebuild dict + ontology
    new_dict = build_automaton(new_entries)
    return new_dict, new_onto, summary


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", required=True, help="Parsed JSONL (sections)")
    ap.add_argument("--base-dict", required=True, help="Bootstrap dict.json")
    ap.add_argument("--base-ontology", required=True, help="Bootstrap ontology.json")
    ap.add_argument("--dict", required=True, help="Output dict.json (checkpoint)")
    ap.add_argument("--ontology", required=True, help="Output ontology.json (checkpoint)")
    ap.add_argument("--config", default="docs/domain/3gpp/config.yaml",
                    help="Domain config.yaml (per-task model routing)")
    ap.add_argument("--model", default=None,
                    help="Fallback model name (overrides config default for all tasks)")
    ap.add_argument("--extract-model", default=None, help="Override extract task model")
    ap.add_argument("--verify-model", default=None, help="Override verify task model")
    ap.add_argument("--relations-model", default=None, help="Override relations task model")
    ap.add_argument("--max-tokens", type=int, default=None,
                    help="Override max_tokens for all tasks (default: from config)")
    ap.add_argument("--max-chars", type=int, default=800)
    ap.add_argument("--limit", type=int, default=0, help="0 = all sections")
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--empty", action="store_true",
                    help="Bootstrap from an EMPTY dict/ontology (ignore --base-dict/--base-ontology)")
    ap.add_argument("--resume", action="store_true",
                    help="Resume from the checkpoint files (--dict/--ontology + .progress.jsonl). "
                         "Without this, a fresh bootstrap is done (base or empty).")
    ap.add_argument("--parallel", action="store_true",
                    help="Run the 3-stage pipeline concurrently across chunks")
    return ap


def main() -> None:
    args = build_parser().parse_args()

    parsed = Path(args.parsed)
    dict_path = Path(args.dict)
    onto_path = Path(args.ontology)

    # Load per-task model routing from the domain pack's config.yaml. Each of
    # the three LLM calls (extract/verify/relations) resolves to its own model
    # config; CLI --*-model / --max-tokens override the config.
    domain_cfg = load_domain(Path(args.config).parent)
    llm_cfg = domain_cfg.llm
    task_configs: dict[str, LLMConfig] = {}
    for task in ("extract", "verify", "relations"):
        cfg = llm_cfg.models.get(task, llm_cfg.default)
        # CLI overrides (model name / max_tokens) win over config.
        override_model = {
            "extract": args.extract_model,
            "verify": args.verify_model,
            "relations": args.relations_model,
        }[task] or args.model
        if override_model:
            cfg = LLMConfig(
                enabled=cfg.enabled,
                model=override_model,
                provider=cfg.provider,
                api_base=cfg.api_base,
                api_key=cfg.api_key,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
                extra=dict(cfg.extra),
            )
        if args.max_tokens:
            cfg = LLMConfig(
                enabled=cfg.enabled,
                model=cfg.model,
                provider=cfg.provider,
                api_base=cfg.api_base,
                api_key=cfg.api_key,
                temperature=cfg.temperature,
                max_tokens=args.max_tokens,
                extra=dict(cfg.extra),
            )
        task_configs[task] = cfg
    fallback_model = args.model or llm_cfg.default.model
    print(
        "Task routing: "
        + ", ".join(f"{t}={c.model}(mt={c.max_tokens})" for t, c in task_configs.items())
    )

    # Bootstrap: resume from checkpoint (--resume), or start fresh from the
    # base dict/ontology, or from an empty dict/ontology (--empty).
    if args.resume:
        if not (dict_path.exists() and onto_path.exists()):
            raise SystemExit(
                f"Resume requested but checkpoint missing: {dict_path} / {onto_path}"
            )
        dictionary = load_dict(dict_path)
        onto = load_ontology(onto_path)
        print(f"Resumed from checkpoint: {len(dictionary.entries)} dict entries, {len(onto.concepts)} concepts")
    elif args.empty:
        dictionary = build_automaton({})
        onto = Ontology()
        print(f"Bootstrap (EMPTY): {len(dictionary.entries)} dict entries, {len(onto.concepts)} concepts")
    else:
        dictionary = load_dict(Path(args.base_dict))
        onto = load_ontology(Path(args.base_ontology))
        print(f"Bootstrap: {len(dictionary.entries)} dict entries, {len(onto.concepts)} concepts")

    sections = load_sections(parsed)
    if args.limit:
        sections = sections[: args.limit]

    # Track which clauses are done (resume support).
    done: set[str] = set()
    log_path = dict_path.with_suffix(".progress.jsonl")
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["clause"])

    if args.parallel:
        from ai_pipeline import ModelQueue, run_pipeline
        queues = {}
        for task in ("extract", "verify", "relations"):
            cfg = task_configs[task]
            queues[task] = ModelQueue(
                f"{cfg.provider or 'ollama'}:{cfg.model}", cfg,
                max_tokens=cfg.max_tokens, maxsize=4)
        try:
            stats = run_pipeline(
                sections, dictionary, onto, queues,
                max_chars=args.max_chars, fallback_model=fallback_model,
                configs=task_configs, dict_path=dict_path,
                onto_path=onto_path, log_path=log_path, done=done,
                on_progress=None)
        finally:
            for q in queues.values():
                q.shutdown()
        print(f"Parallel done: ok={stats['ok']} fail={stats['fail']} "
              f"terms={stats['terms_total']} rels={stats['rels_total']}")
        return

    total = len(sections)
    ok = 0
    fail = 0
    terms_total = 0
    rels_total = 0
    t_start = time.time()

    # Running totals for match-size monitoring (grows as dict/ontology expand).
    match_terms_total = 0
    match_rels_total = 0
    match_cands_total = 0
    # Total content chars actually fed to the LLM (bounded by max_chars per
    # chunk). Sections vary in size, so sec/section is misleading; chars/sec
    # is the fair throughput metric when comparing chunk sizes.
    chars_total = 0
    # Fallback counters: how often each call fell back to deterministic
    # because the model failed (returned empty / malformed after retries).
    fb_extract = 0
    fb_verify = 0
    fb_relations = 0
    # Retry counters: total attempts across all calls (1 = first try, >1 = retry).
    rt_extract = 0
    rt_verify = 0
    rt_relations = 0

    with log_path.open("a", encoding="utf-8") as log:
        for i, section in enumerate(sections):
            if section.clause in done:
                continue
            try:
                result = process_chunk(
                    section, dictionary, onto, fallback_model, args.max_chars,
                    configs=task_configs,
                )
                match = result.pop("_match", {})
                candidates = result.pop("_candidates", None)
                match_terms_total += match.get("known_terms", 0)
                match_rels_total += match.get("known_relations", 0)
                match_cands_total += match.get("candidates", 0)
                chars_total += min(len(section.text), args.max_chars)
                fb = result.get("_fallback", {})
                fb_extract += 1 if fb.get("extract") else 0
                fb_verify += 1 if fb.get("verify") else 0
                fb_relations += 1 if fb.get("relations") else 0
                rt = result.get("_retries", {})
                rt_extract += rt.get("extract", 0)
                rt_verify += rt.get("verify", 0)
                rt_relations += rt.get("relations", 0)
                dictionary, onto, summary = apply_result(
                    result, dictionary, onto, section, candidates
                )
                terms_total += summary["terms_added"]
                rels_total += summary["relations_added"]
                ok += 1
                # checkpoint
                save_dict(dictionary, dict_path)
                save_ontology(onto, onto_path)
                log.write(
                    json.dumps(
                        {
                            "clause": section.clause,
                            "terms_added": summary["terms_added"],
                            "relations_added": summary["relations_added"],
                            "match": match,
                            "result": result,
                        }
                    )
                    + "\n"
                )
                log.flush()
            except Exception as e:  # noqa: BLE001
                fail += 1
                log.write(
                    json.dumps(
                        {"clause": section.clause, "error": str(e), "result": {}}
                    )
                    + "\n"
                )
                log.flush()
            if (i + 1) % 10 == 0 or i == total - 1:
                el = time.time() - t_start
                rate = (ok + fail) / el if el else 0
                chars_rate = chars_total / el if el else 0
                print(
                    f"[{i+1}/{total}] ok={ok} fail={fail} terms={terms_total} "
                    f"rels={rels_total} rate={rate:.2f}/s chars={chars_rate:.0f}/s "
                    f"elapsed={el:.0f}s "
                    f"dict={len(dictionary.entries)} concepts={len(onto.concepts)} "
                    f"match_terms={match_terms_total} match_rels={match_rels_total} "
                    f"match_cands={match_cands_total} "
                    f"fb_extract={fb_extract} fb_verify={fb_verify} "
                    f"fb_relations={fb_relations} "
                    f"rt_extract={rt_extract} rt_verify={rt_verify} "
                    f"rt_relations={rt_relations}",
                    flush=True,
                )
            if args.sleep:
                time.sleep(args.sleep)

    errors = validate_ontology(onto)
    if errors:
        print(f"Validation errors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  - {e}")

    print(
        f"DONE: ok={ok} fail={fail} terms_added={terms_total} "
        f"relations_added={rels_total} final_dict={len(dictionary.entries)} "
        f"final_concepts={len(onto.concepts)} total_time={time.time()-t_start:.0f}s"
    )


if __name__ == "__main__":
    main()
