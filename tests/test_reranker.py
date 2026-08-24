"""Tests for the relationship-aware reranker (Stage 2)."""

from onto3gpp.ontology.schema import Concept, Ontology, Relation
from onto3gpp.runtime.reranker import rerank
from onto3gpp.search.bm25 import SearchResult
from onto3gpp.search.chunker import Chunk


def _chunk(clause: str, text: str) -> Chunk:
    return Chunk(spec="38.300", release="Rel-18", clause=clause, title="", text=text)


def _onto() -> Ontology:
    return Ontology(
        concepts=[
            Concept(id="smf", canonical="SMF", type="network_function"),
            Concept(id="upf", canonical="UPF", type="network_function"),
            Concept(id="pdu_session", canonical="PDU Session", type="procedure"),
        ],
        relations=[
            Relation(source="smf", rel="selects", target="upf"),
        ],
    )


def test_rerank_boosts_chunks_mentioning_related_concepts():
    onto = _onto()
    results = [
        SearchResult(chunk=_chunk("5.1", "The SMF handles the session."), score=0.5),
        SearchResult(chunk=_chunk("5.2", "The UPF forwards packets."), score=0.4),
    ]
    # query mentions SMF; UPF is a related concept → chunk 5.2 should be boosted
    reranked = rerank(results, "SMF", onto)
    assert reranked[0].chunk.clause == "5.2"


def test_rerank_preserves_order_when_no_related_boost():
    onto = _onto()
    results = [
        SearchResult(chunk=_chunk("5.1", "The AMF handles registration."), score=0.5),
        SearchResult(chunk=_chunk("5.2", "The UPF forwards packets."), score=0.4),
    ]
    # query mentions AMF (not in ontology) → no boost, original order preserved
    reranked = rerank(results, "AMF", onto)
    assert reranked[0].chunk.clause == "5.1"
    assert reranked[1].chunk.clause == "5.2"


def test_rerank_returns_empty_for_empty_input():
    onto = _onto()
    assert rerank([], "SMF", onto) == []
