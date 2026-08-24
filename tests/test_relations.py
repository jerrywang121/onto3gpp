"""Tests for relation extraction (Stage 2)."""

from onto3gpp.extract.relations import extract_relations
from onto3gpp.ontology.schema import Concept, Ontology
from onto3gpp.parser import Section


def _onto() -> Ontology:
    return Ontology(
        concepts=[
            Concept(id="smf", canonical="SMF", type="network_function"),
            Concept(id="upf", canonical="UPF", type="network_function"),
            Concept(id="pdu_session", canonical="PDU Session", type="procedure"),
        ]
    )


def _sec(clause: str, title: str, text: str) -> Section:
    return Section(
        spec="23.501", release="Rel-18", clause=clause, title=title, text=text
    )


def test_extracts_selects_relation():
    onto = _onto()
    sections = [_sec("5.6.2", "PDU Session Establishment", "The SMF selects a UPF.")]
    rels = extract_relations(sections, onto)
    assert any(r.source == "smf" and r.rel == "selects" and r.target == "upf" for r in rels)


def test_extracts_establishes_relation():
    onto = _onto()
    sections = [_sec("5.6.1", "General", "The SMF establishes the PDU session.")]
    rels = extract_relations(sections, onto)
    assert any(r.source == "smf" and r.rel == "establishes" and r.target == "pdu_session" for r in rels)


def test_no_relation_when_concepts_absent():
    onto = _onto()
    sections = [_sec("5.7.1", "Registration", "The AMF handles registration.")]
    rels = extract_relations(sections, onto)
    assert rels == []


def test_relation_has_provenance():
    onto = _onto()
    sections = [_sec("5.6.2", "PDU Session Establishment", "The SMF selects a UPF.")]
    rels = extract_relations(sections, onto)
    assert rels[0].provenance.get("clause") == "5.6.2"


def test_no_substring_match_for_short_abbreviations():
    # "re" must not match inside "procedure"; "up" must not match inside "support"
    onto = Ontology(
        concepts=[
            Concept(id="re", canonical="RE", type="abbreviation"),
            Concept(id="up", canonical="UP", type="abbreviation"),
            Concept(id="smf", canonical="SMF", type="network_function"),
        ]
    )
    sections = [_sec("5.6.2", "Procedures", "The SMF supports the procedure.")]
    rels = extract_relations(sections, onto)
    # no relation should be extracted (only SMF is a real whole-word match)
    assert rels == []
