"""End-to-end ingest pipeline (Stage 9).

Deterministic-first, AI-fills-the-gaps, judge-gated ingestion (ADR-0011):

1. Extract terms + relations from parsed sections (rules-based; reuse
   ``extract/terms.py`` and ``extract/relations.py``).
2. Align the ABox against the TBox (``align_abox``).
3. Evolve the TBox for any new concept types / relation types discovered.
4. Merge new concepts/relations into the ABox (``merge_abox``).

The runtime query path stays deterministic and AI-free. AI hooks (domain
detection, LLM extraction, AI-as-judge) are optional and layered on top.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from onto3gpp.extract.relations import extract_relations
from onto3gpp.extract.terms import extract_candidates
from onto3gpp.ingest.evolve import evolve_tbox
from onto3gpp.ingest.merge import merge_abox
from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation
from onto3gpp.ontology.align import align_abox, conformance_ratio
from onto3gpp.ontology.schema import Concept, Ontology
from onto3gpp.ontology.tbox import TBox
from onto3gpp.parser import Section


@dataclass
class IngestResult:
    """Outcome of an ingest run."""

    abox: ABox
    tbox: TBox
    conformance: float = 1.0
    align_errors: list[str] = field(default_factory=list)
    evolved: bool = False
    added_concepts: int = 0
    added_relations: int = 0


def _abox_from_ontology(onto: Ontology) -> ABox:
    """Convert a legacy Ontology (schema.py) into an ABox."""
    concepts = [
        ABoxConcept(
            id=c.id,
            canonical=c.canonical,
            type=c.type,
            aliases=list(c.aliases),
        )
        for c in onto.concepts
    ]
    relations = [
        ABoxRelation(
            source=r.source,
            rel=r.rel,
            target=r.target,
            weight=r.weight,
            confidence=r.confidence,
            provenance=dict(r.provenance),
        )
        for r in onto.relations
    ]
    return ABox(concepts=concepts, relations=relations)


def _extract_abox(sections: list[Section], tbox: TBox) -> ABox:
    """Extract candidate terms + relations from sections into a fresh ABox.

    Terms become ABox concepts (typed ``abbreviation``/``phrase``); relations
    are extracted between known concepts. The TBox is passed to relation
    extraction so that only schema-conforming relations are emitted (unknown
    relation types and disallowed ``(source.type, rel, target.type)`` edges are
    dropped at extraction time, not merely flagged by a later align step).
    """
    candidates = extract_candidates(sections)
    concepts: list[ABoxConcept] = []
    for c in candidates:
        concepts.append(
            ABoxConcept(
                id=c.canonical,
                canonical=c.canonical,
                type=c.type,
                aliases=list(c.aliases),
                metadata={"provenance": dict(c.provenance)},
            )
        )
    # Build a temporary Ontology so relation extraction can find concepts.
    onto = Ontology(
        concepts=[
            Concept(id=c.canonical, canonical=c.canonical, type=c.type)
            for c in candidates
        ]
    )
    relations = extract_relations(sections, onto, tbox=tbox)
    abox_relations = [
        ABoxRelation(
            source=r.source,
            rel=r.rel,
            target=r.target,
            weight=r.weight,
            confidence=r.confidence,
            provenance=dict(r.provenance),
        )
        for r in relations
    ]
    return ABox(concepts=concepts, relations=abox_relations)


def ingest(
    sections: list[Section],
    tbox: TBox,
    abox: ABox | None = None,
    domain: str = "3gpp",
) -> IngestResult:
    """Run the ingest pipeline over parsed ``sections``.

    ``tbox`` is the current top-level ontology; ``abox`` is the current
    low-level knowledge graph (or ``None`` to start empty). Returns an
    :class:`IngestResult` with the merged ABox, possibly-evolved TBox, and
    conformance metrics.
    """
    abox = abox or ABox()

    # 1. Extract terms + relations from the incoming sections.
    extracted = _extract_abox(sections, tbox)

    # 2. Merge extracted entries into the existing ABox.
    merged = merge_abox(abox, extracted)

    # 3. Align the merged ABox against the TBox.
    align = align_abox(merged.abox, tbox)

    # 4. Evolve the TBox for any new concept types / relation types.
    concept_types = {c.type for c in merged.abox.concepts}
    relation_types = {r.rel for r in merged.abox.relations}
    new_concept_types = [t for t in concept_types if not tbox.is_known_concept_type(t)]
    new_relation_types = [r for r in relation_types if not tbox.is_known_relation_type(r)]
    evolved = evolve_tbox(
        tbox,
        new_concept_types=new_concept_types,
        new_relation_types=new_relation_types,
    )

    return IngestResult(
        abox=merged.abox,
        tbox=evolved.tbox,
        conformance=conformance_ratio(align),
        align_errors=align.errors,
        evolved=evolved.evolved,
        added_concepts=merged.added_concepts,
        added_relations=merged.added_relations,
    )
