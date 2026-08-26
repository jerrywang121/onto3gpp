"""TBox — the top-level ontology graph (schema / blueprint) (Stage 7).

The TBox is the *schema* level of the two-level graph (ADR-0010). It holds:

- **concept_types** — the TBox nodes (e.g. ``network_function``,
  ``procedure``).
- **relation_types** — the allowed relation labels.
- **relation_type_constraints** — the TBox edges: ``(source_type, rel,
  target_type)`` triples stating which relation types may connect which
  concept types.

The TBox answers *"is a ``network_function`` allowed to ``select`` a
``procedure``?"*. It is curated in the domain pack by default and evolved by
AI only when evidence demands (ADR-0011). The ABox (instances) is validated
against it by :mod:`onto3gpp.ontology.align`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RelationTypeConstraint:
    """A TBox edge: a relation type allowed between two concept types."""

    source_type: str
    rel: str
    target_type: str


@dataclass
class TBox:
    """The top-level ontology graph (schema / blueprint)."""

    concept_types: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    relation_type_constraints: list[RelationTypeConstraint] = field(default_factory=list)

    def is_known_concept_type(self, concept_type: str) -> bool:
        """Return True if ``concept_type`` is a known TBox node."""
        return concept_type in self.concept_types

    def is_known_relation_type(self, rel: str) -> bool:
        """Return True if ``rel`` is a known TBox relation type."""
        return rel in self.relation_types

    def allows(self, source_type: str, rel: str, target_type: str) -> bool:
        """Return True if the TBox permits ``rel`` between the two types."""
        return (source_type, rel, target_type) in {
            (c.source_type, c.rel, c.target_type) for c in self.relation_type_constraints
        }


def tbox_to_dict(tbox: TBox) -> dict:
    """Serialize a TBox to a JSON-serializable dict."""
    return {
        "concept_types": list(tbox.concept_types),
        "relation_types": list(tbox.relation_types),
        "relation_type_constraints": [
            {
                "source_type": c.source_type,
                "rel": c.rel,
                "target_type": c.target_type,
            }
            for c in tbox.relation_type_constraints
        ],
    }


def tbox_from_dict(data: dict) -> TBox:
    """Deserialize a TBox from a dict produced by :func:`tbox_to_dict`."""
    return TBox(
        concept_types=list(data.get("concept_types", [])),
        relation_types=list(data.get("relation_types", [])),
        relation_type_constraints=[
            RelationTypeConstraint(
                source_type=c["source_type"],
                rel=c["rel"],
                target_type=c["target_type"],
            )
            for c in data.get("relation_type_constraints", [])
        ],
    )
