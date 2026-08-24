"""AI-as-judge improvement loop: log analysis → proposals → review.

This is the *optional* AI-driven improvement path. The runtime is always
deterministic; this module only runs when an LLM client is configured and
enabled in the domain pack.

Flow:
1. **Analyze** search logs (queries + clicks) to find gaps.
2. **Propose** improvements (new terms, aliases, relations) via an LLM using
   the ``propose_improvements.txt`` prompt template.
3. **Review** proposals against the ontology (referential integrity) and
   apply only those that are valid.
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

from onto3gpp.evaluate import GoldQuery, evaluate
from onto3gpp.llm import LLMClient
from onto3gpp.ontology.schema import Ontology, Relation


@dataclass
class ImprovementProposal:
    """A single proposed ontology improvement from the LLM."""

    type: str  # "term" | "alias" | "relation"
    concept: str
    surface: str | None = None
    relation: dict | None = None
    confidence: float = 0.5
    rationale: str = ""


def _load_prompt(name: str, domain_dir: Path) -> str:
    """Load a prompt template from a domain pack's prompts/ directory."""
    path = domain_dir / "prompts" / name
    return path.read_text(encoding="utf-8")


def propose_improvements(
    llm: LLMClient,
    search_logs: list[dict],
    ontology_summary: str,
    domain_dir: Path | None = None,
) -> list[ImprovementProposal]:
    """Ask the LLM to propose ontology improvements from search logs."""
    if domain_dir is not None:
        template = _load_prompt("propose_improvements.txt", domain_dir)
    else:
        template = (
            "You are a knowledge engineer proposing improvements to the {domain} "
            "ontology based on search logs.\n\nSearch logs:\n{search_logs}\n\n"
            "Current ontology (summary):\n{ontology_summary}\n\n"
            "Return JSON with a 'proposals' list."
        )
    prompt = template.format(
        domain="3gpp",
        search_logs=json.dumps(search_logs, indent=2),
        ontology_summary=ontology_summary,
    )
    data = llm.complete_json(prompt)
    proposals: list[ImprovementProposal] = []
    for p in data.get("proposals", []):
        proposals.append(
            ImprovementProposal(
                type=p.get("type", "term"),
                concept=p.get("concept", ""),
                surface=p.get("surface"),
                relation=p.get("relation"),
                confidence=float(p.get("confidence", 0.5)),
                rationale=p.get("rationale", ""),
            )
        )
    return proposals


def apply_proposals(onto: Ontology, proposals: list[ImprovementProposal]) -> int:
    """Apply valid proposals to the ontology, returning the count applied.

    Review rules:
    - **term/alias**: add the surface form as an alias to the concept (if the
      concept exists and the alias is not already present).
    - **relation**: add the relation only if both endpoints are concepts.
    """
    applied = 0
    concept_by_id = {c.id: c for c in onto.concepts}

    for p in proposals:
        if p.type in ("term", "alias"):
            concept = concept_by_id.get(p.concept)
            if concept is None or not p.surface:
                continue
            if p.surface not in concept.aliases:
                concept.aliases.append(p.surface)
                applied += 1
        elif p.type == "relation" and p.relation:
            rel = p.relation
            if rel.get("source") in concept_by_id and rel.get("target") in concept_by_id:
                onto.relations.append(
                    Relation(
                        source=rel["source"],
                        rel=rel.get("rel", "related_to"),
                        target=rel["target"],
                        weight=float(rel.get("weight", 0.7)),
                        confidence=p.confidence,
                        provenance={"rationale": p.rationale},
                    )
                )
                applied += 1
    return applied


def build_search_logs(gold: list[GoldQuery]) -> list[dict]:
    """Convert a gold set into synthetic search logs (query + relevant clicks)."""
    return [
        {"query": gq.query, "clicks": list(gq.relevant_clauses)}
        for gq in gold
    ]


def find_gaps(per_query: list[dict], gold: list[GoldQuery]) -> list[str]:
    """Return the queries whose relevant clause is not in their top-5 results.

    These are the "gaps" the improvement loop should target.
    """
    relevant_by_query = {gq.query: set(gq.relevant_clauses) for gq in gold}
    gaps: list[str] = []
    for row in per_query:
        top = set(row.get("top_clauses", []))
        relevant = relevant_by_query.get(row["query"], set())
        if relevant and not (relevant & top):
            gaps.append(row["query"])
    return gaps


@dataclass
class LoopResult:
    """Outcome of one closed-loop improvement iteration."""

    applied: int
    before_mrr: float | None
    after_mrr: float | None
    gaps: list[str]
    proposals: list[ImprovementProposal]
    promoted: bool = False
    holdout_delta: float | None = None
    regression_log: list[dict] = field(default_factory=list)


def run_improvement_loop(
    index,
    gold: list[GoldQuery],
    ontology: Ontology,
    llm: LLMClient,
    top_k: int = 10,
    domain_dir: Path | None = None,
    holdout_frac: float = 0.3,
    min_delta: float = 0.0,
) -> LoopResult:
    """Run one closed-loop improvement iteration.

    1. Split the gold set into a train set and a hold-out eval set.
    2. Evaluate the train set to find gaps (queries that miss).
    3. Build search logs from the train set.
    4. Ask the LLM to propose improvements.
    5. Auto-judge the proposals against the **hold-out** set: promote only if
       hold-out MRR improves by at least ``min_delta``; otherwise reject.
    6. Report before/after MRR and a regression log.
    """
    train, holdout = split_gold(gold, holdout_frac=holdout_frac)
    before = evaluate(index, train, top_k=top_k, ontology=ontology)
    gaps = find_gaps(before.per_query, train)

    logs = build_search_logs(train)
    summary = (
        f"{len(ontology.concepts)} concepts, {len(ontology.relations)} relations; "
        f"gaps: {', '.join(gaps) if gaps else 'none'}"
    )
    proposals = propose_improvements(
        llm, search_logs=logs, ontology_summary=summary, domain_dir=domain_dir
    )

    # Auto-judge against the hold-out set (no human-in-the-loop).
    judge = auto_judge_proposals(
        index, ontology, proposals, holdout, top_k=top_k, min_delta=min_delta
    )

    after = evaluate(index, train, top_k=top_k, ontology=ontology)
    return LoopResult(
        applied=judge.applied,
        before_mrr=before.mrr,
        after_mrr=after.mrr,
        gaps=gaps,
        proposals=proposals,
        promoted=judge.promoted,
        holdout_delta=judge.delta,
        regression_log=judge.regression_log,
    )


def split_gold(
    gold: list[GoldQuery], holdout_frac: float = 0.3, seed: int = 42
) -> tuple[list[GoldQuery], list[GoldQuery]]:
    """Split a gold set into a train set and a hold-out eval set.

    The improvement loop proposes changes from the *train* set (where it finds
    gaps) but judges them against the *holdout* set, so it can't overfit to
    the queries it saw. Returns ``(train, holdout)``.
    """
    gold = list(gold)
    rng = random.Random(seed)
    rng.shuffle(gold)
    n_holdout = max(1, round(len(gold) * holdout_frac))
    holdout = gold[:n_holdout]
    train = gold[n_holdout:]
    return train, holdout


@dataclass
class AutoJudgeResult:
    """Outcome of auto-judging a batch of proposals against a holdout set."""

    promoted: bool
    delta: float
    before_mrr: float
    after_mrr: float
    applied: int
    regression_log: list[dict]


def auto_judge_proposals(
    index,
    ontology: Ontology,
    proposals: list[ImprovementProposal],
    holdout: list[GoldQuery],
    top_k: int = 10,
    min_delta: float = 0.0,
) -> AutoJudgeResult:
    """Auto-promote or auto-reject proposals using a hold-out eval set.

    The proposals are applied to a *copy* of the ontology, then the holdout
    set is evaluated before and after. If MRR improves by at least
    ``min_delta``, the proposals are promoted (the copy replaces the original
    ontology) and ``promoted`` is True. Otherwise they are rejected and the
    original ontology is left untouched.

    A regression log records per-query MRR before/after so regressions are
    auditable (no human-in-the-loop, but evidence is preserved).
    """
    before = evaluate(index, holdout, top_k=top_k, ontology=ontology)
    before_mrr = before.mrr

    candidate = copy.deepcopy(ontology)
    applied = apply_proposals(candidate, proposals)
    after = evaluate(index, holdout, top_k=top_k, ontology=candidate)
    after_mrr = after.mrr

    delta = after_mrr - before_mrr
    promoted = applied > 0 and delta >= min_delta

    # regression log: per-query MRR before/after
    regression_log: list[dict] = []
    for b, a in zip(before.per_query, after.per_query):
        regression_log.append(
            {
                "query": b["query"],
                "mrr_before": b["mrr"],
                "mrr_after": a["mrr"],
            }
        )

    if promoted:
        # promote: replace the original ontology's contents with the candidate
        ontology.concepts = candidate.concepts
        ontology.relations = candidate.relations

    return AutoJudgeResult(
        promoted=promoted,
        delta=delta,
        before_mrr=before_mrr,
        after_mrr=after_mrr,
        applied=applied,
        regression_log=regression_log,
    )
