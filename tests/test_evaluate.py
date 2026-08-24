"""Tests for the eval harness."""

from onto3gpp.evaluate import GoldQuery, evaluate
from onto3gpp.ontology.schema import Concept, Ontology, Relation
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


def test_evaluate_with_ontology_reranking() -> None:
    chunks = [
        _chunk("5.6.1", "The SMF handles the session."),
        _chunk("5.6.2", "The UPF forwards packets."),
        _chunk("5.7.1", "The AMF handles registration."),
    ]
    index = BM25Index.build(chunks)
    onto = Ontology(
        concepts=[
            Concept(id="smf", canonical="SMF"),
            Concept(id="upf", canonical="UPF"),
        ],
        relations=[Relation(source="smf", rel="selects", target="upf")],
    )
    gold = [GoldQuery(query="SMF", relevant_clauses=["5.6.2"])]
    # without ontology, "SMF" query ranks 5.6.1 first (exact token match)
    plain = evaluate(index, gold)
    # with ontology, UPF (related to SMF) is boosted → 5.6.2 is surfaced into
    # the top results (it shares no exact token with the query)
    reranked = evaluate(index, gold, ontology=onto)
    assert "5.6.2" in reranked.per_query[0]["top_clauses"]
