"""Tests for hold-out auto-judging + auto-promote/auto-reject (Stage 4)."""

from __future__ import annotations

from onto3gpp.evaluate import GoldQuery
from onto3gpp.improve import (
    ImprovementProposal,
    auto_judge_proposals,
    split_gold,
)
from onto3gpp.ontology.schema import Concept, Ontology


class StubIndex:
    """An index whose MRR depends on whether the ontology has an alias."""

    def __init__(self, alias_helps: bool = True):
        self.alias_helps = alias_helps

    def search_structure(self, query, ontology, dictionary=None, top_k=10):
        return []

    def search(self, query, top_k=10):
        return []

    def search_ontology(self, query, ontology, top_k=10):
        return []


def _onto_with_alias(has_alias: bool) -> Ontology:
    c = Concept(id="smf", canonical="SMF")
    if has_alias:
        c.aliases.append("Session Management Function")
    return Ontology(concepts=[c])


def test_split_gold_returns_train_and_holdout():
    gold = [
        GoldQuery(query=f"q{i}", relevant_clauses=[f"{i}.1"]) for i in range(10)
    ]
    train, holdout = split_gold(gold, holdout_frac=0.3, seed=42)
    assert len(train) + len(holdout) == 10
    assert len(holdout) == 3
    # disjoint
    assert not ({q.query for q in train} & {q.query for q in holdout})


def test_auto_judge_promotes_when_holdout_improves():
    # A proposal that adds an alias; the holdout eval improves when applied.
    onto = _onto_with_alias(has_alias=False)
    proposals = [
        ImprovementProposal(
            type="alias",
            concept="smf",
            surface="Session Management Function",
            confidence=0.9,
        )
    ]
    holdout = [GoldQuery(query="smf", relevant_clauses=["5.6.2"])]

    class ImprovingIndex(StubIndex):
        def search_structure(self, query, ontology, dictionary=None, top_k=30):
            # MRR 1.0 if alias present, else 0.0
            has = any("Session Management Function" in c.aliases for c in ontology.concepts)
            if has:
                return [type("R", (), {"chunk": type("C", (), {"clause": "5.6.2", "text": "smf"}), "score": 1.0})()]
            return []

    result = auto_judge_proposals(
        ImprovingIndex(), onto, proposals, holdout, top_k=10
    )
    assert result.promoted is True
    assert result.delta > 0
    # original ontology was mutated (promoted)
    assert any("Session Management Function" in c.aliases for c in onto.concepts)


def test_auto_judge_rejects_when_holdout_regresses():
    onto = _onto_with_alias(has_alias=False)
    proposals = [
        ImprovementProposal(
            type="alias",
            concept="smf",
            surface="Session Management Function",
            confidence=0.9,
        )
    ]
    holdout = [GoldQuery(query="smf", relevant_clauses=["5.6.2"])]

    class RegressingIndex(StubIndex):
        def search_structure(self, query, ontology, dictionary=None, top_k=30):
            # MRR 1.0 WITHOUT the alias, 0.0 WITH it (the proposal hurts).
            has_alias = any("Session Management Function" in c.aliases for c in ontology.concepts)
            if has_alias:
                return []
            return [type("R", (), {"chunk": type("C", (), {"clause": "5.6.2", "text": "smf"}), "score": 1.0})()]

    result = auto_judge_proposals(
        RegressingIndex(), onto, proposals, holdout, min_delta=0.0
    )
    assert result.promoted is False
    assert result.delta < 0
    # original ontology untouched (rejected)
    assert not any("Session Management Function" in c.aliases for c in onto.concepts)
