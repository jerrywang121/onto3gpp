"""Tests for runtime NER (dictionary path, Stage 1)."""

from onto3gpp.compile.dictionary import build_dictionary
from onto3gpp.extract.terms import CandidateTerm
from onto3gpp.runtime.ner import annotate, expand_query


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def _dict():
    terms = [
        _term("SMF", abbreviations=["Session Management Function"]),
        _term("UPF"),
        _term("PDU Session", type="phrase"),
    ]
    return build_dictionary(terms)


def test_annotate_finds_terms():
    d = _dict()
    found = annotate(d, "The SMF selects a UPF")
    assert "SMF" in found
    assert "UPF" in found


def test_annotate_resolves_alias_to_canonical():
    d = _dict()
    found = annotate(d, "The Session Management Function selects a UPF")
    assert "SMF" in found


def test_annotate_finds_phrase():
    d = _dict()
    found = annotate(d, "A PDU session is established")
    assert "PDU Session" in found


def test_expand_query_adds_canonical_terms():
    d = _dict()
    expanded = expand_query(d, "How does the SMF work?")
    assert "smf" in expanded
    # original tokens preserved
    assert "how" in expanded


def test_expand_query_resolves_abbreviation_to_full_name():
    d = _dict()
    expanded = expand_query(d, "What does SMF do?")
    # canonical "SMF" is added (lowercased token)
    assert "smf" in expanded
