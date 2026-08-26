"""Build a HYBRID dict + ontology: full deterministic base + AI-typed concepts.

The deterministic dict/ontology (data/dict.json, data/ontology.json) has full
coverage (5815 entries) but concepts are typed only "abbreviation"/"phrase".
The AI extraction produces TYPED concepts (network_function, procedure, ...)
that feed the reasoner/reranker. This script merges the two:

- Dictionary: start from the full deterministic dict, ADD any AI concepts not
  already present (so coverage is preserved and AI terms are added).
- Ontology: start from the full deterministic ontology, ADD AI-typed concepts
  (with their TBox-valid types) and re-extract relations over the union.

This isolates the AI's contribution: same coverage, but concepts now carry
semantic types that the reasoner/reranker can use.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from onto3gpp.compile.dictionary import Dictionary, DictionaryEntry, build_automaton  # noqa: E402
from onto3gpp.extract.relations import extract_relations  # noqa: E402
from onto3gpp.ontology.schema import (  # noqa: E402
    Concept,
    Ontology,
    ontology_to_dict,
    validate_ontology,
)
from onto3gpp.parser import Section  # noqa: E402


def load_ai_concepts(path: Path) -> dict[str, dict]:
    """Load AI concepts keyed by lowercase canonical."""
    out: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        for c in d.get("concepts", []):
            canonical = c["canonical"].strip()
            if not canonical:
                continue
            key = canonical.lower()
            if key not in out:
                out[key] = {
                    "canonical": canonical,
                    "type": c.get("type", "concept"),
                    "confidence": float(c.get("confidence", 0.5)),
                }
    return out


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-dict", required=True, help="Deterministic dict.json")
    ap.add_argument("--base-ontology", required=True, help="Deterministic ontology.json")
    ap.add_argument("--parsed", required=True, help="Parsed JSONL (for relations)")
    ap.add_argument("--ai", required=True, help="AI extraction JSONL")
    ap.add_argument("--dict", required=True, help="Output hybrid dict.json")
    ap.add_argument("--ontology", required=True, help="Output hybrid ontology.json")
    args = ap.parse_args()

    ai = load_ai_concepts(Path(args.ai))
    sections = load_sections(Path(args.parsed))

    # --- Dictionary: base + AI additions ---
    base_dict = Dictionary.from_dict(json.loads(Path(args.base_dict).read_text(encoding="utf-8")))
    entries: dict[str, DictionaryEntry] = dict(base_dict.entries)
    added = 0
    for key, c in ai.items():
        if key not in {e.surface.lower() for e in entries.values()}:
            entries[c["canonical"]] = DictionaryEntry(
                surface=c["canonical"],
                canonical=c["canonical"],
                type=c["type"],
                aliases=[],
            )
            added += 1
    hybrid_dict = build_automaton(entries)
    Path(args.dict).parent.mkdir(parents=True, exist_ok=True)
    Path(args.dict).write_text(json.dumps(hybrid_dict.to_dict(), indent=2), encoding="utf-8")
    print(f"Hybrid dict: {len(entries)} entries (base {len(base_dict.entries)} + AI {added}) -> {args.dict}")

    # --- Ontology: base concepts + AI-typed concepts ---
    base_onto = json.loads(Path(args.base_ontology).read_text(encoding="utf-8"))
    concepts: dict[str, Concept] = {}
    for c in base_onto.get("concepts", []):
        concepts[c["id"]] = Concept(
            id=c["id"], canonical=c["canonical"], type=c.get("type", "concept"),
            aliases=list(c.get("aliases", [])),
        )
    ai_added = 0
    for key, c in ai.items():
        cid = c["canonical"].lower().replace(" ", "_")
        if cid not in concepts:
            concepts[cid] = Concept(id=cid, canonical=c["canonical"], type=c["type"])
            ai_added += 1
    onto = Ontology(concepts=list(concepts.values()))
    relations = extract_relations(sections, onto)
    onto.relations = relations

    errors = validate_ontology(onto)
    if errors:
        print(f"Validation errors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  - {e}")

    Path(args.ontology).parent.mkdir(parents=True, exist_ok=True)
    Path(args.ontology).write_text(json.dumps(ontology_to_dict(onto), indent=2), encoding="utf-8")
    print(f"Hybrid ontology: {len(onto.concepts)} concepts (base {len(base_onto['concepts'])} + AI {ai_added}), {len(onto.relations)} relations -> {args.ontology}")


if __name__ == "__main__":
    main()
