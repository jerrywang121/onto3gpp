"""TBox evolution (Stage 9).

Gated, auditable evolution of the top-level ontology (ADR-0005, ADR-0011).
New concept types, relation types, and constraints are added conservatively.
A constraint referencing an unknown relation type is dropped (schema drift
guard). Returns a new TBox; the input is not mutated.
"""

from __future__ import annotations

from dataclasses import dataclass

from onto3gpp.ontology.tbox import RelationTypeConstraint, TBox


@dataclass
class EvolveResult:
    """Outcome of a TBox evolution attempt."""

    tbox: TBox
    evolved: bool


def evolve_tbox(
    tbox: TBox,
    new_concept_types: list[str] | None = None,
    new_relation_types: list[str] | None = None,
    new_constraints: list[RelationTypeConstraint] | None = None,
) -> EvolveResult:
    """Evolve a TBox with new types/constraints, returning a new TBox.

    Only genuinely new entries are added. Constraints referencing a relation
    type not in ``relation_types`` are dropped (schema-drift guard). If nothing
    changes, the original TBox is returned unchanged.
    """
    concept_types = list(tbox.concept_types)
    relation_types = list(tbox.relation_types)
    constraints = list(tbox.relation_type_constraints)

    for ct in new_concept_types or []:
        if ct not in concept_types:
            concept_types.append(ct)

    for rt in new_relation_types or []:
        if rt not in relation_types:
            relation_types.append(rt)

    known_rels = set(relation_types)
    for c in new_constraints or []:
        if c.rel not in known_rels:
            continue  # schema-drift guard
        if (c.source_type, c.rel, c.target_type) not in {
            (x.source_type, x.rel, x.target_type) for x in constraints
        }:
            constraints.append(c)

    evolved = (
        concept_types != tbox.concept_types
        or relation_types != tbox.relation_types
        or constraints != tbox.relation_type_constraints
    )
    if not evolved:
        return EvolveResult(tbox=tbox, evolved=False)

    return EvolveResult(
        tbox=TBox(
            concept_types=concept_types,
            relation_types=relation_types,
            relation_type_constraints=constraints,
        ),
        evolved=True,
    )
