"""Tests for the AI-as-judge candidate gate (Stage 1)."""

from onto3gpp.extract.terms import CandidateTerm
from onto3gpp.judge import judge_candidate, JudgeResult


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def test_accepts_supported_term_above_threshold():
    term = _term("SMF", provenance={"spec": "23.501", "clause": "5.6.2"})
    result = judge_candidate(term, threshold=0.5)
    assert isinstance(result, JudgeResult)
    assert result.accepted is True
    assert result.overall_confidence >= 0.5


def test_rejects_term_below_threshold():
    # No provenance → low support → rejected
    term = _term("XYZ", provenance={})
    result = judge_candidate(term, threshold=0.8)
    assert result.accepted is False


def test_threshold_boundary():
    term = _term("SMF", provenance={"spec": "23.501", "clause": "5.6.2"})
    high = judge_candidate(term, threshold=0.99)
    low = judge_candidate(term, threshold=0.0)
    assert high.accepted is False
    assert low.accepted is True


def test_judge_uses_gold_evidence_for_accuracy():
    term = _term("SMF", provenance={"spec": "23.501", "clause": "5.6.2"})
    # gold evidence that mentions SMF → higher accuracy
    with_gold = judge_candidate(
        term, threshold=0.5, gold_evidence=["SMF selects a UPF"]
    )
    without_gold = judge_candidate(term, threshold=0.5, gold_evidence=[])
    assert with_gold.overall_confidence >= without_gold.overall_confidence
