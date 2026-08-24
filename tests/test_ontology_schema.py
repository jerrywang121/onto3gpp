"""Tests for the ontology schema, validation, and merge (Stage 2)."""

from onto3gpp.ontology.schema import (
    Concept,
    Relation,
    Ontology,
    validate_ontology,
    merge_ontologies,
    ontology_to_dict,
    ontology_from_dict,
)


def _concept(cid: str, canonical: str, type: str = "network_function") -> Concept:
    return Concept(id=cid, canonical=canonical, type=type)


def _rel(source: str, rel: str, target: str) -> Relation:
    return Relation(source=source, rel=rel, target=target, weight=0.7, confidence=0.9)


def test_validate_accepts_wellformed():
    onto = Ontology(
        concepts=[_concept("smf", "SMF"), _concept("upf", "UPF")],
        relations=[_rel("smf", "selects", "upf")],
    )
    errors = validate_ontology(onto)
    assert errors == []


def test_validate_rejects_dangling_relation_source():
    onto = Ontology(
        concepts=[_concept("upf", "UPF")],
        relations=[_rel("smf", "selects", "upf")],
    )
    errors = validate_ontology(onto)
    assert any("smf" in e for e in errors)


def test_validate_rejects_dangling_relation_target():
    onto = Ontology(
        concepts=[_concept("smf", "SMF")],
        relations=[_rel("smf", "selects", "upf")],
    )
    errors = validate_ontology(onto)
    assert any("upf" in e for e in errors)


def test_validate_rejects_duplicate_concept_id():
    onto = Ontology(
        concepts=[_concept("smf", "SMF"), _concept("smf", "SMF2")],
        relations=[],
    )
    errors = validate_ontology(onto)
    assert any("duplicate" in e.lower() for e in errors)


def test_merge_combines_concepts_and_relations():
    a = Ontology(
        concepts=[_concept("smf", "SMF")],
        relations=[_rel("smf", "selects", "upf")],
    )
    b = Ontology(
        concepts=[_concept("upf", "UPF")],
        relations=[_rel("upf", "forwards", "packet")],
    )
    merged = merge_ontologies([a, b])
    assert len(merged.concepts) == 2
    assert len(merged.relations) == 2


def test_merge_deduplicates_shared_concepts():
    a = Ontology(concepts=[_concept("smf", "SMF")], relations=[])
    b = Ontology(concepts=[_concept("smf", "SMF")], relations=[])
    merged = merge_ontologies([a, b])
    assert len(merged.concepts) == 1


def test_ontology_roundtrip_serialization():
    onto = Ontology(
        concepts=[_concept("smf", "SMF"), _concept("upf", "UPF")],
        relations=[_rel("smf", "selects", "upf")],
    )
    data = ontology_to_dict(onto)
    restored = ontology_from_dict(data)
    assert len(restored.concepts) == 2
    assert len(restored.relations) == 1
    assert restored.relations[0].source == "smf"
    assert restored.relations[0].rel == "selects"
    assert restored.relations[0].target == "upf"
