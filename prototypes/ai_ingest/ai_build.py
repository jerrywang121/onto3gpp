"""Build a dictionary + ontology from AI-extracted typed concepts (prototype).

Reads the AI extraction JSONL (spec/clause/title/concepts[]) and produces:
- a compiled dictionary (dict.json format) from the AI concepts
- an ontology (ontology.json format) with AI-typed concepts + verb-extracted
  relations (relations still come from the deterministic extractor, since the
  AI relation prompt is unreliable; the AI's contribution is the TYPED
  concepts, which feed the reasoner/reranker).

Usage:
  python ai_build.py --ai /tmp/ai_full.jsonl --parsed data/parsed/38300-i30.jsonl \
      --dict /tmp/ai_dict.json --ontology /tmp/ai_ontology.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from onto3gpp.compile.dictionary import build_dictionary  # noqa: E402
from onto3gpp.extract.relations import extract_relations  # noqa: E402
from onto3gpp.extract.terms import CandidateTerm  # noqa: E402
from onto3gpp.ontology.schema import (  # noqa: E402
    Concept,
    Ontology,
    ontology_to_dict,
    validate_ontology,
)
from onto3gpp.parser import Section  # noqa: E402


def load_ai_concepts(path: Path) -> list[CandidateTerm]:
    """Load AI-extracted concepts into CandidateTerm objects (typed)."""
    terms: dict[str, CandidateTerm] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        for c in d.get("concepts", []):
            canonical = c["canonical"].strip()
            if not canonical:
                continue
            ctype = c.get("type", "concept")
            conf = float(c.get("confidence", 0.5))
            key = canonical.lower()
            if key not in terms or conf > terms[key].confidence:
                terms[key] = CandidateTerm(
                    canonical=canonical,
                    type=ctype,
                    confidence=conf,
                    provenance={"spec": d.get("spec", ""), "clause": d.get("clause", "")},
                )
    return list(terms.values())


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
    ap.add_argument("--parsed", required=True, help="Parsed JSONL (for relations)")
    ap.add_argument("--ai", required=True, help="AI extraction JSONL")
    ap.add_argument("--dict", required=True, help="Output dict.json")
    ap.add_argument("--ontology", required=True, help="Output ontology.json")
    args = ap.parse_args()

    terms = load_ai_concepts(Path(args.ai))
    sections = load_sections(Path(args.parsed))

    # Build dictionary from AI terms.
    dictionary = build_dictionary(terms)
    Path(args.dict).parent.mkdir(parents=True, exist_ok=True)
    Path(args.dict).write_text(
        json.dumps(dictionary.to_dict(), indent=2), encoding="utf-8"
    )
    print(f"Dictionary: {len(dictionary.entries)} entries -> {args.dict}")

    # Build ontology: AI-typed concepts + verb-extracted relations.
    concepts: dict[str, Concept] = {}
    for t in terms:
        cid = t.canonical.lower().replace(" ", "_")
        if cid not in concepts:
            concepts[cid] = Concept(
                id=cid,
                canonical=t.canonical,
                type=t.type,
                aliases=list(t.aliases),
            )
    onto = Ontology(concepts=list(concepts.values()))
    relations = extract_relations(sections, onto)
    onto.relations = relations

    errors = validate_ontology(onto)
    if errors:
        print(f"Validation errors ({len(errors)}):")
        for e in errors[:20]:
            print(f"  - {e}")

    Path(args.ontology).parent.mkdir(parents=True, exist_ok=True)
    Path(args.ontology).write_text(
        json.dumps(ontology_to_dict(onto), indent=2), encoding="utf-8"
    )
    print(f"Ontology: {len(onto.concepts)} concepts, {len(onto.relations)} relations -> {args.ontology}")


if __name__ == "__main__":
    main()
