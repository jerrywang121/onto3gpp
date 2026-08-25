"""Tests for ABox merge / conflict resolution (Stage 9)."""

from onto3gpp.ingest.merge import merge_abox
from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation


def _concept(cid, canonical, ctype="network_function"):
    return ABoxConcept(id=cid, canonical=canonical, type=ctype)


def _rel(source, rel, target, confidence=0.9):
    return ABoxRelation(source=source, rel=rel, target=target, confidence=confidence)


def test_merge_adds_new_concepts_and_relations():
    existing = ABox(concepts=[_concept("smf", "SMF")], relations=[])
    incoming = ABox(
        concepts=[_concept("upf", "UPF")],
        relations=[_rel("smf", "uses", "upf")],
    )
    result = merge_abox(existing, incoming)
    assert result.added_concepts == 1
    assert result.added_relations == 1
    assert {c.canonical for c in result.abox.concepts} == {"SMF", "UPF"}
    assert len(result.abox.relations) == 1


def test_merge_dedupes_by_canonical_case_insensitive():
    existing = ABox(concepts=[_concept("smf", "SMF")], relations=[])
    incoming = ABox(concepts=[_concept("smf2", "smf")], relations=[])
    result = merge_abox(existing, incoming)
    assert result.merged_concepts == 1
    assert result.added_concepts == 0
    assert len(result.abox.concepts) == 1


def test_merge_keeps_higher_confidence_relation():
    existing = ABox(
        concepts=[_concept("smf", "SMF"), _concept("upf", "UPF")],
        relations=[_rel("smf", "uses", "upf", confidence=0.5)],
    )
    incoming = ABox(
        concepts=[_concept("smf", "SMF"), _concept("upf", "UPF")],
        relations=[_rel("smf", "uses", "upf", confidence=0.9)],
    )
    result = merge_abox(existing, incoming)
    assert result.duplicate_relations == 1
    assert result.abox.relations[0].confidence == 0.9


def test_merge_records_type_conflict():
    existing = ABox(concepts=[_concept("smf", "SMF", "network_function")], relations=[])
    incoming = ABox(concepts=[_concept("smf", "SMF", "procedure")], relations=[])
    result = merge_abox(existing, incoming)
    assert result.conflicts == 1
    # existing type wins (first-wins)
    assert result.abox.concepts[0].type == "network_function"
