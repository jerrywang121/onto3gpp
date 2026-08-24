"""Tests for structure-aware boosts (Stage 3)."""

from onto3gpp.runtime.structure import (
    build_ancestor_map,
    structure_boost,
)
from onto3gpp.search.bm25 import SearchResult
from onto3gpp.search.chunker import Chunk


def _chunk(clause: str, title: str, text: str) -> Chunk:
    return Chunk(spec="38.300", release="Rel-18", clause=clause, title=title, text=text)


def _chunks() -> list[Chunk]:
    return [
        _chunk("9.2.3.2", "Handover", "The source gNB prepares the target."),
        _chunk("9.2.3.2.1", "C-Plane Handling", "Preparation messages are exchanged."),
        _chunk("9.2.1.1", "Cell Selection", "The UE selects a cell."),
        _chunk("16.15.5", "Non-Homogeneous support", "PDU set based handling."),
    ]


def test_build_ancestor_map():
    chunks = _chunks()
    amap = build_ancestor_map(chunks)
    # 9.2.3.2.1's ancestors include 9.2.3.2, 9.2.3, 9.2, 9
    assert "9.2.3.2" in amap["9.2.3.2.1"]
    assert "9.2.3" in amap["9.2.3.2.1"]
    # 9.2.3.2's ancestors are 9, 9.2, 9.3
    assert amap["9.2.3.2"] == ["9", "9.2", "9.2.3"]


def test_structure_boost_boosts_title_match():
    chunks = _chunks()
    results = [
        SearchResult(chunk=chunks[0], score=0.1),
        SearchResult(chunk=chunks[1], score=0.1),
        SearchResult(chunk=chunks[2], score=0.1),
        SearchResult(chunk=chunks[3], score=0.1),
    ]
    # query mentions "handover" → the chunk titled "Handover" (and its child)
    # should be boosted above the others
    boosted = structure_boost(results, "handover", chunks)
    assert boosted[0].chunk.clause == "9.2.3.2"
    assert boosted[1].chunk.clause == "9.2.3.2.1"


def test_structure_boost_boosts_ancestor_title_match():
    chunks = _chunks()
    results = [
        SearchResult(chunk=chunks[1], score=0.1),  # 9.2.3.2.1 C-Plane Handling
        SearchResult(chunk=chunks[3], score=0.1),  # 16.15.5
    ]
    # query "handover" → 9.2.3.2.1's ancestor 9.2.3.2 is titled "Handover"
    boosted = structure_boost(results, "handover", chunks)
    assert boosted[0].chunk.clause == "9.2.3.2.1"


def test_structure_boost_no_match_preserves_order():
    chunks = _chunks()
    results = [
        SearchResult(chunk=chunks[0], score=0.5),
        SearchResult(chunk=chunks[1], score=0.4),
    ]
    boosted = structure_boost(results, "zzz", chunks)
    assert boosted[0].chunk.clause == "9.2.3.2"
    assert boosted[1].chunk.clause == "9.2.3.2.1"
