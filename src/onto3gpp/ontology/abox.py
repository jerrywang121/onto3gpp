"""ABox — the low-level knowledge graph (instances) (Stage 7).

The ABox is the *instance* level of the two-level graph (ADR-0010): concrete
concept objects, typed relations, metadata, and provenance. It extends the
existing :class:`onto3gpp.ontology.schema.Concept` /
:class:`onto3gpp.ontology.schema.Relation` model with richer metadata and
provenance. This is what the runtime consumes.

The ABox is validated against the TBox (schema) by
:mod:`onto3gpp.ontology.align`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ABoxConcept:
    """A concrete concept object in the low-level knowledge graph."""

    id: str
    canonical: str
    type: str = "concept"
    aliases: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class ABoxRelation:
    """A typed relation between two ABox concepts, with provenance."""

    source: str
    rel: str
    target: str
    weight: float = 0.7
    confidence: float = 0.9
    provenance: dict = field(default_factory=dict)


@dataclass
class ABox:
    """A collection of ABox concepts and relations."""

    concepts: list[ABoxConcept] = field(default_factory=list)
    relations: list[ABoxRelation] = field(default_factory=list)


def abox_to_dict(abox: ABox) -> dict:
    """Serialize an ABox to a JSON-serializable dict."""
    return {
        "concepts": [
            {
                "id": c.id,
                "canonical": c.canonical,
                "type": c.type,
                "aliases": list(c.aliases),
                "metadata": dict(c.metadata),
            }
            for c in abox.concepts
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
            for r in abox.relations
        ],
    }


def abox_from_dict(data: dict) -> ABox:
    """Deserialize an ABox from a dict produced by :func:`abox_to_dict`."""
    concepts = [
        ABoxConcept(
            id=c["id"],
            canonical=c["canonical"],
            type=c.get("type", "concept"),
            aliases=list(c.get("aliases", [])),
            metadata=dict(c.get("metadata", {})),
        )
        for c in data.get("concepts", [])
    ]
    relations = [
        ABoxRelation(
            source=r["source"],
            rel=r["rel"],
            target=r["target"],
            weight=r.get("weight", 0.7),
            confidence=r.get("confidence", 0.9),
            provenance=dict(r.get("provenance", {})),
        )
        for r in data.get("relations", [])
    ]
    return ABox(concepts=concepts, relations=relations)
