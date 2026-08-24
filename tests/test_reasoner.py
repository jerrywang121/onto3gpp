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


def test_reason_resolves_alias_to_canonical():
    onto = Ontology(
        concepts=[
            Concept(id="handover", canonical="handover", aliases=["HO", "Intra-NR RAN handover"]),
            Concept(id="ue", canonical="UE"),
        ],
        relations=[
            Relation(source="handover", rel="handles", target="ue"),
        ],
    )
    # query mentions the alias "HO" → should resolve to canonical "handover"
    plan = reason("How is HO handled?", onto)
    assert "handover" in plan.primary_terms
    # related terms from the resolved concept's neighbors
    assert "UE" in plan.related_terms


def test_reason_alias_does_not_match_other_concept():
    onto = Ontology(
        concepts=[
            Concept(id="handover", canonical="handover", aliases=["HO"]),
            Concept(id="ho_thing", canonical="HO Thing"),
        ],
    )
    plan = reason("HO", onto)
    # "HO" alias resolves to handover, not to the "HO Thing" canonical
    assert "handover" in plan.primary_terms


# --- max_hops: multi-hop reasoning ---


def _chain_onto() -> Ontology:
    """A 3-node chain: AMF -- SMF -- UPF, so 2-hop reasoning from AMF reaches UPF."""
    return Ontology(
        concepts=[
            Concept(id="amf", canonical="AMF"),
            Concept(id="smf", canonical="SMF"),
            Concept(id="upf", canonical="UPF"),
        ],
        relations=[
            Relation(source="amf", rel="rel", target="smf"),
            Relation(source="smf", rel="rel", target="upf"),
        ],
    )


def test_reason_default_is_one_hop():
    onto = _chain_onto()
    plan = reason("AMF", onto)
    # default max_hops=1: SMF is a 1-hop neighbor, UPF is not
    assert "SMF" in plan.related_terms
    assert "UPF" not in plan.related_terms


def test_reason_two_hops_reaches_second_degree_neighbor():
    onto = _chain_onto()
    plan = reason("AMF", onto, max_hops=2)
    assert "SMF" in plan.related_terms
    assert "UPF" in plan.related_terms


def test_reason_max_hops_zero_returns_no_related_terms():
    onto = _chain_onto()
    plan = reason("AMF", onto, max_hops=0)
    assert "AMF" in plan.primary_terms
    assert plan.related_terms == []


def test_reason_multi_hop_does_not_repeat_primary():
    onto = _chain_onto()
    plan = reason("AMF", onto, max_hops=2)
    # the primary concept itself must not appear as a related term
    assert "AMF" not in plan.related_terms
