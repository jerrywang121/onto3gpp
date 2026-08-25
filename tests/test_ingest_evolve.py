"""Tests for TBox evolution (Stage 9)."""

from onto3gpp.ingest.evolve import evolve_tbox
from onto3gpp.ontology.tbox import TBox, RelationTypeConstraint


def _tbox():
    return TBox(
        concept_types=["network_function", "procedure"],
        relation_types=["uses", "is_a"],
        relation_type_constraints=[
            RelationTypeConstraint("network_function", "uses", "procedure"),
        ],
    )


def test_evolve_adds_new_concept_type():
    tbox = _tbox()
    result = evolve_tbox(tbox, new_concept_types=["interface"])
    assert result.evolved is True
    assert "interface" in result.tbox.concept_types


def test_evolve_adds_new_relation_type():
    tbox = _tbox()
    result = evolve_tbox(tbox, new_relation_types=["connects"])
    assert result.evolved is True
    assert "connects" in result.tbox.relation_types


def test_evolve_adds_constraint():
    tbox = _tbox()
    result = evolve_tbox(
        tbox,
        new_relation_types=["connects"],
        new_constraints=[RelationTypeConstraint("interface", "connects", "network_function")],
    )
    assert result.evolved is True
    assert result.tbox.allows("interface", "connects", "network_function")


def test_evolve_noop_when_nothing_new():
    tbox = _tbox()
    result = evolve_tbox(tbox, new_concept_types=["network_function"])
    assert result.evolved is False
    assert result.tbox is tbox


def test_evolve_ignores_unknown_relation_type_in_constraint():
    # A constraint referencing a relation type not in relation_types is dropped.
    tbox = _tbox()
    result = evolve_tbox(
        tbox,
        new_constraints=[RelationTypeConstraint("network_function", "nope", "procedure")],
    )
    assert result.evolved is False
