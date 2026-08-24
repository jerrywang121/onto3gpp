"""Tests for the ontology reasoner (Stage 2)."""

from onto3gpp.ontology.schema import Concept, Ontology, Relation
from onto3gpp.runtime.reasoner import SearchPlan, reason


def _onto() -> Ontology:
    return Ontology(
        concepts=[
            Concept(id="smf", canonical="SMF", type="network_function"),
            Concept(id="upf", canonical="UPF", type="network_function"),
            Concept(id="pdu_session", canonical="PDU Session", type="procedure"),
            Concept(id="amf", canonical="AMF", type="network_function"),
        ],
        relations=[
            Relation(source="smf", rel="selects", target="upf"),
            Relation(source="smf", rel="establishes", target="pdu_session"),
        ],
    )


def test_reason_returns_primary_and_related_terms():
    onto = _onto()
    plan = reason("SMF", onto)
    assert isinstance(plan, SearchPlan)
    # primary terms include the query concept
    assert "SMF" in plan.primary_terms
    # related terms include 1-hop neighbors (UPF, PDU Session)
    assert "UPF" in plan.related_terms
    assert "PDU Session" in plan.related_terms
    # AMF is not related to SMF → not in related terms
    assert "AMF" not in plan.related_terms


def test_reason_no_concepts_returns_empty_plan():
    onto = _onto()
    plan = reason("unknown query", onto)
    assert plan.primary_terms == []
    assert plan.related_terms == []


def test_reason_related_terms_are_deduped():
    onto = Ontology(
        concepts=[
            Concept(id="a", canonical="AMF"),
            Concept(id="b", canonical="SMF"),
        ],
        relations=[
            Relation(source="a", rel="rel", target="b"),
            Relation(source="a", rel="rel2", target="b"),
        ],
    )
    plan = reason("AMF", onto)
    assert plan.related_terms.count("SMF") == 1
