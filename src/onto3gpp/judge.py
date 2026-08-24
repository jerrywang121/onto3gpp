"""AI-as-judge candidate gate (Stage 1).

Deterministic, AI-free scoring of candidate terms. An optional LLM path can
be added later (see docs/domain/3gpp/prompts/judge_candidates.txt).

Scoring dimensions (mirroring the LLM judge prompt):
- **support**: how well the term is backed by provenance (spec + clause).
- **accuracy**: whether the term appears in the ground-truth gold evidence.
- **non_redundancy**: whether the term is a distinct, non-trivial surface form.

The overall confidence is a weighted combination. A candidate is accepted
when overall_confidence >= threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

from onto3gpp.extract.terms import CandidateTerm


@dataclass
class JudgeResult:
    """Outcome of judging a candidate term."""

    support: float
    accuracy: float
    non_redundancy: float
    overall_confidence: float
    accepted: bool
    reason: str


def _support(term: CandidateTerm) -> float:
    """Score how well the term is backed by provenance."""
    prov = term.provenance or {}
    if prov.get("spec") and prov.get("clause"):
        return 0.9
    if prov.get("spec") or prov.get("clause"):
        return 0.5
    return 0.1


def _accuracy(term: CandidateTerm, gold_evidence: list[str]) -> float:
    """Score whether the term appears in the gold evidence."""
    if not gold_evidence:
        return 0.5  # neutral when no gold evidence available
    canonical = term.canonical.lower()
    for ev in gold_evidence:
        if canonical in ev.lower():
            return 0.9
    return 0.3


def _non_redundancy(term: CandidateTerm) -> float:
    """Score whether the term is a distinct, non-trivial surface form."""
    # Abbreviations are distinct surface forms; short/trivial ones are less so.
    if term.type == "abbreviation":
        return 0.8 if len(term.canonical) >= 2 else 0.3
    # Phrases are distinct if they have 2+ words
    return 0.8 if len(term.canonical.split()) >= 2 else 0.4


def judge_candidate(
    term: CandidateTerm,
    threshold: float = 0.8,
    gold_evidence: list[str] | None = None,
) -> JudgeResult:
    """Judge a candidate term deterministically and return a JudgeResult.

    When gold evidence is available, accuracy is a strong signal and the
    weights are balanced. When it is absent (bootstrap), the judge relies
    primarily on provenance support so well-supported terms can still pass.
    """
    gold_evidence = gold_evidence or []
    support = _support(term)
    accuracy = _accuracy(term, gold_evidence)
    non_redundancy = _non_redundancy(term)

    if gold_evidence:
        # Balanced: support and accuracy dominate.
        overall = 0.4 * support + 0.4 * accuracy + 0.2 * non_redundancy
    else:
        # Bootstrap: rely on provenance support.
        overall = 0.8 * support + 0.2 * non_redundancy

    accepted = overall >= threshold

    reason = (
        f"support={support:.2f} accuracy={accuracy:.2f} "
        f"non_redundancy={non_redundancy:.2f}"
    )
    return JudgeResult(
        support=support,
        accuracy=accuracy,
        non_redundancy=non_redundancy,
        overall_confidence=overall,
        accepted=accepted,
        reason=reason,
    )


def gate_candidates(
    candidates: list[CandidateTerm],
    threshold: float = 0.8,
    gold_evidence: list[str] | None = None,
) -> list[CandidateTerm]:
    """Filter candidates, keeping only those accepted by the judge."""
    return [
        c
        for c in candidates
        if judge_candidate(c, threshold=threshold, gold_evidence=gold_evidence).accepted
    ]
