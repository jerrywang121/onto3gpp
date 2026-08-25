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
from onto3gpp.extract.relations import extract_relations  # noqa: E402
from onto3gpp.extract.terms import extract_candidates  # noqa: E402
from onto3gpp.ontology.schema import (  # noqa: E402
    Concept,
    Ontology,
    ontology_from_dict,
    ontology_to_dict,
    validate_ontology,
)
from onto3gpp.parser import Section  # noqa: E402

CONCEPT_TYPES = (
    "network_function, procedure, information_element, interface, protocol, "
    "qos, architecture, security"
)

# NOTE: the local ollama models return EMPTY when given an exclusion list
# ("do NOT re-add these"). The reliable format is a plain "extract concepts"
# prompt. So we use that, and filter out already-known concepts
# DETERMINISTICALLY in apply_result (which skips existing canonicals). This
# gives the "AI fills gaps" behavior without relying on the flaky model to
# respect an exclusion list.
#
# We DO feed the deterministic candidates and the known terms (from the
# current dict/ontology) into the prompt as POSITIVE reference context, so the
# AI can see what the deterministic extractor found and what is already known.
# The model is asked to identify NEW concepts the deterministic extractor
# missed. Already-known concepts are still filtered deterministically in
# apply_result as a safety net.
PROMPT_TEMPLATE = """You are a knowledge engineer building a 3GPP ontology. Given the specification text below, identify NEW technical concepts (terms) that are NOT already covered by the deterministic extractor or the existing knowledge base.

The deterministic extractor already found these candidate terms:
{candidates}

The existing knowledge base already contains these terms:
{known}

Text:
{text}

List each NEW concept with its type (choose from: {types}) and a confidence 0-1. Focus on concepts the deterministic extractor missed. Return ONLY a JSON object of the form:
{{"concepts": [{{"canonical": "term", "type": "type", "confidence": 0.9}}]}}"""


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


def _fmt_candidates(candidates) -> str:
    if not candidates:
        return "(none)"
    return "\n".join(f"- {c.canonical} [{c.type}]" for c in candidates)


def _fmt_known(known: list[str]) -> str:
    if not known:
        return "(none)"
    return "\n".join(f"- {k}" for k in known)


def process_chunk(
    section: Section,
    d: Dictionary,
    onto: Ontology,
    model: str,
    max_chars: int = 800,
) -> dict:
    """Run the a/b/c/d progressive step for one chunk. Returns the AI result.

    (a) deterministic extraction -> candidate terms (used for context)
    (b) known terms in this chunk (from the current dict)
    (c) AI extracts concepts from the chunk (reliable format); already-known
        concepts are filtered out deterministically in apply_result.

    The returned dict includes `_match` metadata: the number of known terms
    matched in this chunk (from the current dict) and the number of known
    relations matched (from the current ontology). These grow as the dict and
    ontology expand, so we monitor them to detect context/performance growth.
    """
    # (a) deterministic extraction
    candidates = extract_candidates([section])
    # (b) known terms in this chunk (from the current dict)
    known = d.find(section.text)
    # (b2) known relations in this chunk (from the current ontology)
    known_rels = [
        r
        for r in onto.relations
        if r.source in known or r.target in known
    ]
    # (c) AI decides what to add, given the chunk + deterministic candidates +
    #     known terms as context. Already-known concepts are filtered out
    #     deterministically in apply_result as a safety net.
    prompt = PROMPT_TEMPLATE.format(
        text=section.text[:max_chars],
        types=CONCEPT_TYPES,
        candidates=_fmt_candidates(candidates),
        known=_fmt_known(known),
    )
    result = complete_json(prompt, model, max_tokens=1024, attempts=10)
    result["_match"] = {
        "known_terms": len(known),
        "known_relations": len(known_rels),
        "candidates": len(candidates),
    }
    return result


def apply_result(
    result: dict,
    dictionary: Dictionary,
    onto: Ontology,
    section: Section,
) -> tuple[Dictionary, Ontology, dict]:
    """Apply the AI's extracted concepts to the dict + ontology.

    Only NEW concepts (not already in the dict/ontology) are added — this is
    the deterministic "AI fills gaps" filter. Relations are re-extracted
    deterministically over the updated ontology (the reliable path).

    Returns (new_dict, new_ontology, summary).
    """
    summary = {"terms_added": 0, "relations_added": 0, "terms_updated": 0}

    # --- add terms (only NEW ones) ---
    existing_surfaces = {e.surface.lower() for e in dictionary.entries.values()}
    existing_ids = {c.id for c in onto.concepts}
    existing_canonical_lower = {c.canonical.lower() for c in onto.concepts}

    new_entries: dict[str, DictionaryEntry] = dict(dictionary.entries)
    new_concepts: dict[str, Concept] = {c.id: c for c in onto.concepts}

    for t in result.get("concepts", []):
        canonical = (t.get("canonical") or "").strip()
        if not canonical:
            continue
        ctype = t.get("type", "concept")
        if canonical.lower() in existing_canonical_lower:
            continue  # already known — skip (AI fills gaps only)
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

    # --- relations: re-extract deterministically over the updated ontology ---
    # Preserve previously accumulated relations, add this chunk's new ones.
    new_onto = Ontology(concepts=list(new_concepts.values()))
    chunk_relations = extract_relations([section], new_onto)
    existing_rels = {(r.source, r.rel, r.target) for r in onto.relations}
    new_relations = list(onto.relations)
    added_rels = 0
    for r in chunk_relations:
        if (r.source, r.rel, r.target) not in existing_rels:
            new_relations.append(r)
            existing_rels.add((r.source, r.rel, r.target))
            added_rels += 1
    summary["relations_added"] = added_rels
    new_onto.relations = new_relations

    # rebuild dict + ontology
    new_dict = build_automaton(new_entries)
    return new_dict, new_onto, summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", required=True, help="Parsed JSONL (sections)")
    ap.add_argument("--base-dict", required=True, help="Bootstrap dict.json")
    ap.add_argument("--base-ontology", required=True, help="Bootstrap ontology.json")
    ap.add_argument("--dict", required=True, help="Output dict.json (checkpoint)")
    ap.add_argument("--ontology", required=True, help="Output ontology.json (checkpoint)")
    ap.add_argument("--model", default="deepseek-v4-flash:0731-cloud")
    ap.add_argument("--max-chars", type=int, default=800)
    ap.add_argument("--limit", type=int, default=0, help="0 = all sections")
    ap.add_argument("--sleep", type=float, default=0.0)
    args = ap.parse_args()

    parsed = Path(args.parsed)
    dict_path = Path(args.dict)
    onto_path = Path(args.ontology)

    # Bootstrap: start from base dict/ontology, or resume from checkpoint.
    if dict_path.exists() and onto_path.exists():
        dictionary = load_dict(dict_path)
        onto = load_ontology(onto_path)
        print(f"Resumed from checkpoint: {len(dictionary.entries)} dict entries, {len(onto.concepts)} concepts")
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

    with log_path.open("a", encoding="utf-8") as log:
        for i, section in enumerate(sections):
            if section.clause in done:
                continue
            try:
                result = process_chunk(section, dictionary, onto, args.model, args.max_chars)
                match = result.pop("_match", {})
                match_terms_total += match.get("known_terms", 0)
                match_rels_total += match.get("known_relations", 0)
                match_cands_total += match.get("candidates", 0)
                dictionary, onto, summary = apply_result(result, dictionary, onto, section)
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
                print(
                    f"[{i+1}/{total}] ok={ok} fail={fail} terms={terms_total} "
                    f"rels={rels_total} rate={rate:.2f}/s elapsed={el:.0f}s "
                    f"dict={len(dictionary.entries)} concepts={len(onto.concepts)} "
                    f"match_terms={match_terms_total} match_rels={match_rels_total} "
                    f"match_cands={match_cands_total}",
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
