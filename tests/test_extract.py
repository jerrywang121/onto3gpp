"""Tests for candidate term extraction (Stage 1)."""

from onto3gpp.extract.terms import extract_candidates
from onto3gpp.parser import Section


def _sec(clause: str, title: str, text: str) -> Section:
    return Section(
        spec="23.501", release="Rel-18", clause=clause, title=title, text=text
    )


def test_extracts_abbreviations():
    sections = [_sec("5.6.1", "General", "The SMF establishes the PDU session.")]
    cands = extract_candidates(sections)
    abbrs = {c.canonical for c in cands if c.type == "abbreviation"}
    assert "SMF" in abbrs


def test_extracts_phrase_from_title():
    sections = [_sec("5.6.1", "PDU Session", "A PDU session is established.")]
    cands = extract_candidates(sections)
    phrases = {c.canonical for c in cands if c.type == "phrase"}
    assert "PDU Session" in phrases


def test_links_abbreviation_to_phrase():
    sections = [
        _sec(
            "5.6.1",
            "General",
            "The Session Management Function (SMF) establishes the PDU session.",
        )
    ]
    cands = extract_candidates(sections)
    smf = next(c for c in cands if c.canonical == "Session Management Function")
    assert "SMF" in smf.abbreviations


def test_standalone_abbreviation_is_own_term():
    sections = [_sec("5.6.1", "General", "The SMF selects a UPF.")]
    cands = extract_candidates(sections)
    smf = next(c for c in cands if c.canonical == "SMF")
    assert smf.type == "abbreviation"


def test_phrase_abbreviation_also_standalone():
    # "PDU Session" phrase and "PDU" abbreviation both extracted
    sections = [_sec("5.6.1", "PDU Session", "The PDU session is established.")]
    cands = extract_candidates(sections)
    canonicals = {c.canonical for c in cands}
    assert "PDU Session" in canonicals
    assert "PDU" in canonicals


def test_allcaps_stopwords_not_extracted_as_abbreviations():
    # Common English words in all-caps (THE, TO, OF, AND, OR, AN, ON, FROM)
    # must not be extracted as abbreviation concepts.
    sections = [
        _sec(
            "5.6.1",
            "General",
            "THE SMF forwards TO the UPF OF the network AND OR the session.",
        )
    ]
    cands = extract_candidates(sections)
    abbrs = {c.canonical for c in cands if c.type == "abbreviation"}
    assert "SMF" in abbrs
    assert "UPF" in abbrs
    for stop in ("THE", "TO", "OF", "AND", "OR"):
        assert stop not in abbrs
