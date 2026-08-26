"""Tests for the TBox (top-level ontology graph) schema (Stage 7)."""

from onto3gpp.ontology.tbox import (
    TBox,
    RelationTypeConstraint,
    tbox_from_dict,
    tbox_to_dict,
)


def _tbox() -> TBox:
    return TBox(
        concept_types=["network_function", "procedure", "information_element"],
        relation_types=["uses", "selects", "part_of", "is_a"],
        relation_type_constraints=[
            RelationTypeConstraint("network_function", "uses", "network_function"),
            RelationTypeConstraint("network_function", "selects", "network_function"),
            RelationTypeConstraint("procedure", "uses", "information_element"),
            RelationTypeConstraint("procedure", "part_of", "procedure"),
        ],
    )


def test_tbox_roundtrip():
    tbox = _tbox()
    data = tbox_to_dict(tbox)
    assert data["concept_types"] == [
        "network_function",
        "procedure",
        "information_element",
    ]
    assert data["relation_types"] == ["uses", "selects", "part_of", "is_a"]
    assert data["relation_type_constraints"] == [
        {"source_type": "network_function", "rel": "uses", "target_type": "network_function"},
        {"source_type": "network_function", "rel": "selects", "target_type": "network_function"},
        {"source_type": "procedure", "rel": "uses", "target_type": "information_element"},
        {"source_type": "procedure", "rel": "part_of", "target_type": "procedure"},
    ]
    restored = tbox_from_dict(data)
    assert restored == tbox


def test_tbox_from_dict_defaults():
    tbox = tbox_from_dict({"concept_types": ["a"], "relation_types": ["r"]})
    assert tbox.relation_type_constraints == []


def test_tbox_allows_relation():
    tbox = _tbox()
    assert tbox.allows("network_function", "uses", "network_function")
    assert tbox.allows("procedure", "part_of", "procedure")
    assert not tbox.allows("procedure", "selects", "information_element")
    assert not tbox.allows("network_function", "uses", "information_element")


def test_tbox_known_concept_type():
    tbox = _tbox()
    assert tbox.is_known_concept_type("network_function")
    assert not tbox.is_known_concept_type("bogus")


def test_tbox_known_relation_type():
    tbox = _tbox()
    assert tbox.is_known_relation_type("uses")
    assert not tbox.is_known_relation_type("bogus")
