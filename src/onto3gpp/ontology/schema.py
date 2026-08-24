"""Ontology schema, validation, and merge (Stage 2).

A lightweight ontology: concepts (with canonical terms + types) and typed
relations between them. Validation ensures referential integrity (no dangling
relation endpoints, no duplicate concept ids). Merge combines multiple
ontologies (e.g. per-spec) into one, deduplicating shared concepts.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Concept:
    """A concept in the ontology."""

    id: str
    canonical: str
    type: str = "concept"
    aliases: list[str] = field(default_factory=list)


@dataclass
class Relation:
    """A typed relation between two concepts."""

    source: str
    rel: str
    target: str
    weight: float = 0.7
    confidence: float = 0.9
    provenance: dict = field(default_factory=dict)


@dataclass
class Ontology:
    """A collection of concepts and relations."""

    concepts: list[Concept] = field(default_factory=list)
    relations: list[Relation] = field(default_factory=list)


def validate_ontology(onto: Ontology) -> list[str]:
    """Return a list of validation errors (empty if the ontology is valid)."""
    errors: list[str] = []
    concept_ids = {c.id for c in onto.concepts}

    # duplicate concept ids
    seen: set[str] = set()
    for c in onto.concepts:
        if c.id in seen:
            errors.append(f"duplicate concept id: {c.id}")
        seen.add(c.id)

    # dangling relation endpoints
    for r in onto.relations:
        if r.source not in concept_ids:
            errors.append(f"relation source not a concept: {r.source}")
        if r.target not in concept_ids:
            errors.append(f"relation target not a concept: {r.target}")

    return errors


def merge_ontologies(ontologies: list[Ontology]) -> Ontology:
    """Merge multiple ontologies into one, deduplicating shared concepts.

    Relations are concatenated (dedup by (source, rel, target)).
    """
    concepts: dict[str, Concept] = {}
    relations: dict[tuple[str, str, str], Relation] = {}

    for onto in ontologies:
        for c in onto.concepts:
            concepts.setdefault(c.id, c)
        for r in onto.relations:
            relations.setdefault((r.source, r.rel, r.target), r)

    return Ontology(concepts=list(concepts.values()), relations=list(relations.values()))


def ontology_to_dict(onto: Ontology) -> dict:
    """Serialize an ontology to a JSON-serializable dict."""
    return {
        "concepts": [
            {
                "id": c.id,
                "canonical": c.canonical,
                "type": c.type,
                "aliases": list(c.aliases),
            }
            for c in onto.concepts
        ],
        "relations": [
            {
                "source": r.source,
                "rel": r.rel,
                "target": r.target,
                "weight": r.weight,
                "confidence": r.confidence,
                "provenance": dict(r.provenance),
            }
            for r in onto.relations
        ],
    }


def ontology_from_dict(data: dict) -> Ontology:
    """Deserialize an ontology from a dict produced by :func:`ontology_to_dict`."""
    concepts = [
        Concept(
            id=c["id"],
            canonical=c["canonical"],
            type=c.get("type", "concept"),
            aliases=list(c.get("aliases", [])),
        )
        for c in data.get("concepts", [])
    ]
    relations = [
        Relation(
            source=r["source"],
            rel=r["rel"],
            target=r["target"],
            weight=r.get("weight", 0.7),
            confidence=r.get("confidence", 0.9),
            provenance=dict(r.get("provenance", {})),
        )
        for r in data.get("relations", [])
    ]
    return Ontology(concepts=concepts, relations=relations)
