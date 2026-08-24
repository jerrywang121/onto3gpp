"""Tests for the BM25 index and search."""

from onto3gpp.search.bm25 import BM25Index
from onto3gpp.search.chunker import Chunk


def _chunk(clause: str, text: str) -> Chunk:
    return Chunk(spec="23.501", release="Rel-18", clause=clause, title="", text=text)


def test_bm25_index_and_search() -> None:
    chunks = [
        _chunk("5.6.1", "The PDU session is established by the SMF."),
        _chunk("5.6.2", "The UPF forwards user plane packets."),
        _chunk("5.7.1", "Registration procedure involves the AMF."),
    ]
    index = BM25Index.build(chunks)
    results = index.search("PDU session establishment")
    assert len(results) > 0
    # The chunk mentioning PDU session should rank first
    assert results[0].chunk.clause == "5.6.1"


def test_bm25_empty_query() -> None:
    chunks = [_chunk("5.6.1", "Some text here.")]
    index = BM25Index.build(chunks)
    assert index.search("") == []
