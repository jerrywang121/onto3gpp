"""Tests for query expansion → BM25 (Stage 1)."""

from onto3gpp.compile.dictionary import build_dictionary
from onto3gpp.extract.terms import CandidateTerm
from onto3gpp.parser import Section
from onto3gpp.search.bm25 import BM25Index
from onto3gpp.search.chunker import chunk_sections


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def _index():
    sections = [
        Section(
            spec="23.501",
            release="Rel-18",
            clause="5.6.2",
            title="PDU Session Establishment",
            text="The Session Management Function selects a UPF.",
        ),
        Section(
            spec="23.501",
            release="Rel-18",
            clause="5.7.1",
            title="Registration",
            text="The AMF handles registration.",
        ),
        Section(
            spec="23.501",
            release="Rel-18",
            clause="5.8.1",
            title="QoS Flow",
            text="A QoS flow is identified by a QFI.",
        ),
        Section(
            spec="23.501",
            release="Rel-18",
            clause="5.9.1",
            title="N2 Interface",
            text="The N2 interface connects the RAN to the AMF.",
        ),
        Section(
            spec="23.501",
            release="Rel-18",
            clause="5.10.1",
            title="Handover",
            text="Handover moves the UE between cells.",
        ),
    ]
    return BM25Index.build(chunk_sections(sections))


def test_expanded_search_uses_canonical_terms():
    d = build_dictionary([_term("SMF", abbreviations=["Session Management Function"])])
    index = _index()
    # Query "SMF" alone doesn't match "Session Management Function" text
    plain = index.search("SMF", top_k=5)
    expanded = index.search_expanded("SMF", d, top_k=5)
    # Expanded search should surface the PDU session clause
    assert any(r.chunk.clause == "5.6.2" for r in expanded)


def test_expanded_search_returns_results():
    d = build_dictionary([_term("SMF", abbreviations=["Session Management Function"])])
    index = _index()
    results = index.search_expanded("SMF", d, top_k=5)
    assert len(results) > 0
