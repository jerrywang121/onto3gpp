"""Tests for the end-to-end ingest pipeline (Stage 9)."""

from onto3gpp.ingest.pipeline import ingest
from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation
from onto3gpp.ontology.tbox import TBox, RelationTypeConstraint


def _tbox():
    return TBox(
        concept_types=["network_function", "procedure"],
        relation_types=["uses", "is_a"],
        relation_type_constraints=[
            RelationTypeConstraint("network_function", "uses", "procedure"),
        ],
    )


def _abox():
    return ABox(
        concepts=[ABoxConcept(id="smf", canonical="SMF", type="network_function")],
        relations=[],
    )


def test_ingest_returns_abox_and_tbox():
    result = ingest(
        sections=[],
        tbox=_tbox(),
        abox=_abox(),
        domain="3gpp",
    )
    assert result.abox is not None
    assert result.tbox is not None


def test_ingest_aligns_and_reports_conformance():
    # A conforming relation: network_function uses procedure.
    result = ingest(
        sections=[],
        tbox=_tbox(),
        abox=ABox(
            concepts=[
                ABoxConcept(id="smf", canonical="SMF", type="network_function"),
                ABoxConcept(id="pdu", canonical="PDU Session", type="procedure"),
            ],
            relations=[
                ABoxRelation(source="smf", rel="uses", target="pdu"),
            ],
        ),
        domain="3gpp",
    )
    assert result.conformance == 1.0
    assert result.align_errors == []


def test_ingest_evolves_tbox_for_new_concept_type():
    # A concept with an unknown type triggers TBox evolution.
    result = ingest(
        sections=[],
        tbox=_tbox(),
        abox=ABox(
            concepts=[ABoxConcept(id="n3", canonical="N3", type="interface")],
            relations=[],
        ),
        domain="3gpp",
    )
    assert result.tbox.is_known_concept_type("interface")
    assert result.evolved is True
