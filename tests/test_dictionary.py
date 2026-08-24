"""Tests for the ontology compiler (Stage 1)."""

from onto3gpp.compile.dictionary import (
    build_dictionary,
    Dictionary,
    DictionaryEntry,
)
from onto3gpp.extract.terms import CandidateTerm


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def test_build_dictionary_creates_entries():
    terms = [
        _term("SMF", abbreviations=["Session Management Function"]),
        _term("PDU Session", type="phrase"),
    ]
    d = build_dictionary(terms)
    assert isinstance(d, Dictionary)
    assert len(d.entries) == 3  # SMF + alias "Session Management Function" + "PDU Session"


def test_dictionary_maps_abbreviation_to_canonical():
    terms = [_term("SMF", abbreviations=["Session Management Function"])]
    d = build_dictionary(terms)
    # canonical "SMF" maps to itself
    assert d.entries["SMF"].canonical == "SMF"
    # alias "Session Management Function" maps to canonical "SMF"
    assert d.entries["Session Management Function"].canonical == "SMF"


def test_dictionary_has_aho_corasick_automaton():
    terms = [_term("SMF"), _term("UPF")]
    d = build_dictionary(terms)
    assert d.automaton is not None
    # automaton should find "SMF" in text
    found = d.find("The SMF selects a UPF")
    assert "SMF" in found
    assert "UPF" in found


def test_dictionary_find_returns_aliases():
    terms = [_term("SMF", abbreviations=["Session Management Function"])]
    d = build_dictionary(terms)
    found = d.find("The Session Management Function selects a UPF")
    assert "SMF" in found  # alias resolves to canonical


def test_dictionary_serialize_roundtrip():
    terms = [_term("SMF", abbreviations=["Session Management Function"])]
    d = build_dictionary(terms)
    data = d.to_dict()
    d2 = Dictionary.from_dict(data)
    assert d2.entries == d.entries
    assert d2.find("SMF") == d.find("SMF")
