"""Tests for the closed-loop improvement (search logs -> proposals -> re-eval)."""

from __future__ import annotations

from onto3gpp.evaluate import GoldQuery
from onto3gpp.improve import (
    build_search_logs,
    find_gaps,
    run_improvement_loop,
)
from onto3gpp.llm import LLMClient, LLMConfig
from onto3gpp.ontology.schema import Ontology, Concept


class FakeLLM(LLMClient):
    def __init__(self, payload: str):
        super().__init__(LLMConfig(enabled=True))
        self.payload = payload

    def _call(self, prompt: str) -> str:
        return self.payload


def test_build_search_logs_from_gold():
    gold = [
        GoldQuery(query="cell reselection", relevant_clauses=["9.2.1.2"]),
        GoldQuery(query="handover", relevant_clauses=["9.2.3.2"]),
    ]
    logs = build_search_logs(gold)
    assert len(logs) == 2
    assert logs[0]["query"] == "cell reselection"
    assert logs[0]["clicks"] == ["9.2.1.2"]


def test_find_gaps_returns_failing_queries():
    # per_query: query + top_clauses; a gap is when no relevant clause is in top-5
    per_query = [
        {"query": "q1", "top_clauses": ["1.1", "1.2"]},
        {"query": "q2", "top_clauses": ["9.2.1.2", "1.1"]},
    ]
    gold = [
        GoldQuery(query="q1", relevant_clauses=["9.2.1.2"]),
        GoldQuery(query="q2", relevant_clauses=["9.2.1.2"]),
    ]
    gaps = find_gaps(per_query, gold)
    assert gaps == ["q1"]


def test_run_improvement_loop_returns_metrics_and_proposals():
    # A minimal index stub that always returns the same top clauses.
    class StubIndex:
        def search(self, query, top_k=10):
            return []

        def search_ontology(self, query, ontology, top_k=10):
            return []

    onto = Ontology(concepts=[Concept(id="smf", canonical="SMF")])
    llm = FakeLLM(
        '{"proposals": [{"type": "alias", "concept": "smf",'
        ' "surface": "Session Management Function", "confidence": 0.9,'
        ' "rationale": "full name"}]}'
    )
    gold = [GoldQuery(query="smf", relevant_clauses=["5.6.2"])]

    result = run_improvement_loop(
        index=StubIndex(),
        gold=gold,
        ontology=onto,
        llm=llm,
    )
    assert result.applied == 1
    assert "Session Management Function" in onto.concepts[0].aliases
    assert result.before_mrr is not None
    assert result.after_mrr is not None
