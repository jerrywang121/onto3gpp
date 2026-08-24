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
from pathlib import Path
from typing import TYPE_CHECKING

from onto3gpp.extract.terms import CandidateTerm

if TYPE_CHECKING:
    from onto3gpp.llm import LLMClient


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


def llm_judge_candidate(
    llm: LLMClient,
    term: CandidateTerm,
    text: str = "",
    gold_evidence: list[str] | None = None,
    domain_dir: Path | None = None,
) -> JudgeResult:
    """Judge a candidate using an external AI model (AI-as-judge path).

    Uses the ``judge_candidates.txt`` prompt template from the domain pack.
    Falls back to the deterministic judge if the LLM response is malformed.
    """
    from onto3gpp.llm import LLMDisabledError

    if domain_dir is not None:
        template = (domain_dir / "prompts" / "judge_candidates.txt").read_text(
            encoding="utf-8"
        )
    else:
        template = (
            "You are an AI judge evaluating a candidate ontology entry for the "
            "{domain} domain.\n\nCandidate:\n{candidate}\n\nSource text:\n{text}\n\n"
            "Ground-truth gold set:\n{gold_evidence}\n\n"
            "Return JSON with support, accuracy, non_redundancy, "
            "overall_confidence, accepted, reason."
        )
    prompt = template.format(
        domain="3gpp",
        candidate=term.canonical,
        text=text,
        gold_evidence="\n".join(gold_evidence or []),
    )
    try:
        data = llm.complete_json(prompt)
    except (LLMDisabledError, ValueError, KeyError):
        # Fall back to the deterministic judge when the LLM is unavailable.
        return judge_candidate(term, gold_evidence=gold_evidence)

    support = float(data.get("support", 0.0))
    accuracy = float(data.get("accuracy", 0.0))
    non_redundancy = float(data.get("non_redundancy", 0.0))
    overall = float(data.get("overall_confidence", 0.0))
    accepted = bool(data.get("accepted", overall >= 0.8))
    reason = str(data.get("reason", ""))
    return JudgeResult(
        support=support,
        accuracy=accuracy,
        non_redundancy=non_redundancy,
        overall_confidence=overall,
        accepted=accepted,
        reason=reason,
    )
