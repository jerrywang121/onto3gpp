"""ABox merge / conflict resolution (Stage 9).

Deterministic similarity first: merge new concepts/relations into an existing
ABox, deduplicating by canonical (case-insensitive) and keeping the higher
confidence relation. Type conflicts are recorded and resolved first-wins.
An AI judge can be added later for ambiguous cases (ADR-0011).
"""

from __future__ import annotations

from dataclasses import dataclass

from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation


@dataclass
class MergeResult:
    """Outcome of merging an incoming ABox into an existing one."""

    abox: ABox
    added_concepts: int = 0
    merged_concepts: int = 0
    added_relations: int = 0
    duplicate_relations: int = 0
    conflicts: int = 0


def _canonical_key(canonical: str) -> str:
    return canonical.strip().lower()


def merge_abox(existing: ABox, incoming: ABox) -> MergeResult:
    """Merge ``incoming`` into ``existing``, deduplicating and resolving
    conflicts. Returns a new ABox (the input ABoxes are not mutated)."""
    concepts: dict[str, ABoxConcept] = {}
    for c in existing.concepts:
        concepts[_canonical_key(c.canonical)] = c

    relations: dict[tuple[str, str, str], ABoxRelation] = {}
    for r in existing.relations:
        relations[(r.source, r.rel, r.target)] = r

    added_concepts = 0
    merged_concepts = 0
    added_relations = 0
    duplicate_relations = 0
    conflicts = 0

    for c in incoming.concepts:
        key = _canonical_key(c.canonical)
        if key in concepts:
            merged_concepts += 1
            existing_c = concepts[key]
            if existing_c.type != c.type:
                conflicts += 1
            # first-wins: keep the existing concept, but merge aliases
            for alias in c.aliases:
                if alias not in existing_c.aliases:
                    existing_c.aliases.append(alias)
        else:
            concepts[key] = c
            added_concepts += 1

    for r in incoming.relations:
        key = (r.source, r.rel, r.target)
        if key in relations:
            duplicate_relations += 1
            if r.confidence > relations[key].confidence:
                relations[key] = r
        else:
            relations[key] = r
            added_relations += 1

    return MergeResult(
        abox=ABox(concepts=list(concepts.values()), relations=list(relations.values())),
        added_concepts=added_concepts,
        merged_concepts=merged_concepts,
        added_relations=added_relations,
        duplicate_relations=duplicate_relations,
        conflicts=conflicts,
    )
