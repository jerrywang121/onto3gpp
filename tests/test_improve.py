"""Tests for the AI-as-judge improvement loop (log analysis → proposals → review)."""

from __future__ import annotations

from onto3gpp.improve import (
    ImprovementProposal,
    apply_proposals,
    propose_improvements,
)
from onto3gpp.llm import LLMClient, LLMConfig
from onto3gpp.ontology.schema import Ontology, Concept, Relation


class FakeLLM(LLMClient):
    """A scripted LLM that returns a fixed JSON payload."""

    def __init__(self, payload: str):
        super().__init__(LLMConfig(enabled=True))
        self.payload = payload
        self.prompts: list[str] = []

    def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.payload


def test_propose_improvements_parses_proposals():
    llm = FakeLLM(
        '{"proposals": ['
        '{"type": "term", "concept": "SMF", "surface": "Session Management Function",'
        ' "confidence": 0.9, "rationale": "full name"},'
        '{"type": "relation", "concept": "SMF",'
        ' "relation": {"source": "SMF", "rel": "uses", "target": "UPF"},'
        ' "confidence": 0.8, "rationale": "data path"}]}'
    )
    proposals = propose_improvements(
        llm,
        search_logs=[{"query": "smf upf", "clicks": ["4.2.3"]}],
        ontology_summary="SMF, UPF",
    )
    assert len(proposals) == 2
    assert proposals[0].type == "term"
    assert proposals[0].concept == "SMF"
    assert proposals[0].surface == "Session Management Function"
    assert proposals[1].type == "relation"
    assert proposals[1].relation == {"source": "SMF", "rel": "uses", "target": "UPF"}


def test_propose_improvements_passes_logs_into_prompt():
    llm = FakeLLM('{"proposals": []}')
    propose_improvements(llm, search_logs=[{"query": "q1"}], ontology_summary="S")
    assert any("q1" in p for p in llm.prompts)


def test_apply_proposals_adds_term_alias():
    onto = Ontology(concepts=[Concept(id="SMF", canonical="SMF")])
    proposals = [
        ImprovementProposal(
            type="term",
            concept="SMF",
            surface="Session Management Function",
            confidence=0.9,
            rationale="full name",
        )
    ]
    apply_proposals(onto, proposals)
    assert "Session Management Function" in onto.concepts[0].aliases


def test_apply_proposals_adds_relation():
    onto = Ontology(
        concepts=[Concept(id="SMF", canonical="SMF"), Concept(id="UPF", canonical="UPF")]
    )
    proposals = [
        ImprovementProposal(
            type="relation",
            concept="SMF",
            relation={"source": "SMF", "rel": "uses", "target": "UPF"},
            confidence=0.8,
            rationale="data path",
        )
    ]
    apply_proposals(onto, proposals)
    assert len(onto.relations) == 1
    assert onto.relations[0].rel == "uses"


def test_apply_proposals_skips_relation_with_dangling_endpoint():
    onto = Ontology(concepts=[Concept(id="SMF", canonical="SMF")])
    proposals = [
        ImprovementProposal(
            type="relation",
            concept="SMF",
            relation={"source": "SMF", "rel": "uses", "target": "MISSING"},
            confidence=0.8,
            rationale="bad",
        )
    ]
    apply_proposals(onto, proposals)
    assert onto.relations == []
