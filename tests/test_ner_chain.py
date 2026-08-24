"""Tests for the Level 0-4 NER fallback chain (Stage 5).

The chain resolves query terms to canonical concepts, falling back through
increasingly fuzzy levels:
  L0 dictionary (exact Aho-Corasick)
  L1 rules (abbreviations / title phrases)
  L2 small CPU model (fuzzy matcher for ambiguous phrases)
  L3 resolver (alias -> canonical via ontology)
  L4 reasoning (ontology graph expansion)
"""

from onto3gpp.compile.dictionary import build_dictionary
from onto3gpp.extract.terms import CandidateTerm
from onto3gpp.ontology.schema import Concept, Ontology, Relation
from onto3gpp.runtime.ner_chain import (
    NERChain,
    NERMatch,
    fuzzy_similarity,
    resolve_chain,
)


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def _dict():
    terms = [
        _term("SMF", abbreviations=["Session Management Function"]),
        _term("UPF"),
        _term("PDU Session", type="phrase"),
        _term("Handover", type="phrase"),
    ]
    return build_dictionary(terms)


def _onto():
    return Ontology(
        concepts=[
            Concept(id="smf", canonical="SMF", aliases=["Session Management Function"]),
            Concept(id="upf", canonical="UPF"),
            Concept(id="pdu_session", canonical="PDU Session"),
            Concept(id="handover", canonical="Handover", aliases=["HO"]),
            # only in the ontology, not the dictionary — exercises L2 fuzzy
            Concept(id="qos_flow", canonical="QoS Flow"),
        ],
        relations=[
            Relation(source="smf", rel="selects", target="upf"),
            Relation(source="smf", rel="establishes", target="pdu_session"),
        ],
    )


# --- fuzzy matcher (the "small CPU model") ---


def test_fuzzy_similarity_handles_typo():
    # "handover" vs "handover procedure" should be similar (shared bigrams)
    assert fuzzy_similarity("handover", "handover procedure") > 0.5
    # unrelated terms should be low
    assert fuzzy_similarity("handover", "smf") < 0.3


def test_fuzzy_similarity_identity_is_one():
    assert fuzzy_similarity("handover", "handover") == 1.0


# --- Level 0: dictionary exact ---


def test_chain_l0_exact_dictionary_match():
    chain = NERChain(_dict(), _onto())
    matches = chain.annotate("The SMF selects a UPF")
    # SMF and UPF resolved at L0 (exact dictionary)
    canonicals = {m.canonical for m in matches}
    assert "SMF" in canonicals
    assert "UPF" in canonicals
    for m in matches:
        if m.canonical in ("SMF", "UPF"):
            assert m.level == 0


# --- L2: fuzzy matcher resolves ambiguous phrases ---


def test_chain_l2_fuzzy_resolves_ambiguous_phrase():
    # "qos flow" is not in the dictionary exactly, but the fuzzy matcher
    # should resolve it to the "QoS Flow" concept (ontology-only).
    chain = NERChain(_dict(), _onto())
    matches = chain.annotate("qos flow")
    canonicals = {m.canonical for m in matches}
    assert "QoS Flow" in canonicals
    qos = next(m for m in matches if m.canonical == "QoS Flow")
    assert qos.level == 2


# --- L3: resolver (alias -> canonical) ---


def test_chain_l3_resolves_alias_via_ontology():
    chain = NERChain(_dict(), _onto())
    # "HO" is an alias of Handover in the ontology; not in the dictionary
    matches = chain.annotate("HO")
    canonicals = {m.canonical for m in matches}
    assert "Handover" in canonicals
    ho = next(m for m in matches if m.canonical == "Handover")
    assert ho.level == 3


# --- L4: reasoning (ontology expansion) ---


def test_chain_l4_expands_related_concepts():
    chain = NERChain(_dict(), _onto())
    # "SMF" resolves at L0; its 1-hop neighbors (UPF, PDU Session) are added
    # at L4 via ontology reasoning
    matches = chain.annotate("SMF")
    canonicals = {m.canonical for m in matches}
    assert "SMF" in canonicals
    assert "UPF" in canonicals
    assert "PDU Session" in canonicals
    upf = next(m for m in matches if m.canonical == "UPF")
    assert upf.level == 4


# --- standalone resolve_chain ---


def test_resolve_chain_returns_matches():
    matches = resolve_chain("SMF", _dict(), _onto())
    assert isinstance(matches, list)
    assert all(isinstance(m, NERMatch) for m in matches)
    assert any(m.canonical == "SMF" for m in matches)


def test_resolve_chain_empty_query():
    matches = resolve_chain("", _dict(), _onto())
    assert matches == []


def _chain(dictionary, onto):
    return NERChain(dictionary, onto)
