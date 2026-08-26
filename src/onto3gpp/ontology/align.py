"""TBox/ABox constraint checker (align.py) (Stage 7).

Validates that ABox (instance) entries conform to the TBox (schema). A
relation conforms when:

- both endpoints are known ABox concepts,
- the source concept's type is a known TBox concept type,
- the relation type is a known TBox relation type,
- the ``(source.type, rel, target.type)`` triple is an allowed TBox edge.

The conformance ratio is the Stage 7 gate metric: the share of ABox relations
that satisfy the TBox.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from onto3gpp.ontology.abox import ABox
from onto3gpp.ontology.tbox import TBox


@dataclass
class AlignResult:
    """The outcome of aligning an ABox against a TBox."""

    errors: list[str] = field(default_factory=list)
    conforming_relations: int = 0
    total_relations: int = 0


def align_abox(abox: ABox, tbox: TBox) -> AlignResult:
    """Validate an ABox against a TBox, returning an :class:`AlignResult`."""
    errors: list[str] = []
    concept_ids = {c.id for c in abox.concepts}
    concept_type = {c.id: c.type for c in abox.concepts}

    # Concept-level checks.
    for c in abox.concepts:
        if not tbox.is_known_concept_type(c.type):
            errors.append(f"concept '{c.id}' has unknown type '{c.type}'")

    conforming = 0
    for r in abox.relations:
        if r.source not in concept_ids:
            errors.append(f"relation source not a concept: {r.source}")
            continue
        if r.target not in concept_ids:
            errors.append(f"relation target not a concept: {r.target}")
            continue
        if not tbox.is_known_relation_type(r.rel):
            errors.append(f"relation '{r.rel}' is not a known relation type")
            continue
        src_type = concept_type[r.source]
        tgt_type = concept_type[r.target]
        if tbox.allows(src_type, r.rel, tgt_type):
            conforming += 1
        else:
            errors.append(
                f"constraint violation: {src_type} {r.rel} {tgt_type} "
                f"(not allowed by TBox)"
            )

    return AlignResult(
        errors=errors,
        conforming_relations=conforming,
        total_relations=len(abox.relations),
    )


def conformance_ratio(result: AlignResult) -> float:
    """Return the share of relations that conform to the TBox (1.0 if none)."""
    if result.total_relations == 0:
        return 1.0
    return result.conforming_relations / result.total_relations
