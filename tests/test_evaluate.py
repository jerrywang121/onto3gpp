"""Tests for the eval harness."""

from onto3gpp.evaluate import GoldQuery, evaluate
from onto3gpp.search.bm25 import BM25Index
from onto3gpp.search.chunker import Chunk


def _chunk(clause: str, text: str) -> Chunk:
    return Chunk(spec="23.501", release="Rel-18", clause=clause, title="", text=text)


def test_evaluate_returns_metrics() -> None:
    chunks = [
        _chunk("5.6.1", "The PDU session is established by the SMF."),
        _chunk("5.6.2", "The UPF forwards user plane packets."),
        _chunk("5.7.1", "Registration procedure involves the AMF."),
    ]
    index = BM25Index.build(chunks)
    gold = [
        GoldQuery(query="PDU session establishment", relevant_clauses=["5.6.1"]),
        GoldQuery(query="UPF user plane", relevant_clauses=["5.6.2"]),
    ]
    result = evaluate(index, gold)
    assert result.num_queries == 2
    assert 0.0 <= result.mrr <= 1.0
    assert 0.0 <= result.ndcg_at_10 <= 1.0
    assert 0.0 <= result.recall_at_10 <= 1.0
