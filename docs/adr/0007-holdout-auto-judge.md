# ADR-0007: Hold-out Auto-Judge for the Improvement Loop

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 4 (AI-as-Judge Improvement Loop)

## Context

The improvement loop proposes ontology changes (terms, aliases, relations)
from search-log analysis and must decide whether to **promote** or **reject**
them with **no human-in-the-loop**. If the loop evaluates proposals against the
same gold queries it used to find gaps, it can **overfit**: a change that helps
the seen queries may hurt unseen ones. We need an evidence-based, auditable
gate.

## Decision

Split the gold set into a **train** set and a **hold-out** set:

- `split_gold(gold, holdout_frac=0.3, seed=42)` — deterministic shuffle, then
  the first `holdout_frac` become the hold-out set.
- The loop proposes improvements from **train** gaps (queries that miss in the
  train set).
- `auto_judge_proposals` applies the proposals to a **deep copy** of the
  ontology, evaluates the **hold-out** set before and after, and:
  - **Promotes** (replaces the original ontology) iff hold-out MRR improves by
    at least `min_delta` (default 0.0) and at least one proposal applied.
  - **Rejects** otherwise, leaving the original ontology untouched.
- A **regression log** records per-query MRR before/after for every judged
  batch, so regressions are auditable.

## Alternatives considered

1. **Evaluate on the same gold set used for gap-finding.** Rejected: overfits
   to the seen queries; a change that fixes one gap could regress others with
   no signal.
2. **Human review of every proposal.** Rejected: violates the core principle
   of no human-in-the-loop (AGENTS.md §0.2).
3. **Hard-delete rejected proposals.** Rejected: rejected proposals are simply
   not applied; the ontology is left as-is, so nothing is lost and the change
   can be re-proposed later.

## Consequences

- **No overfitting:** promotion is gated on unseen hold-out queries.
- **Auditable:** the regression log preserves per-query evidence for every
  decision, satisfying "evidence before assertions" without human review.
- **Deterministic:** `split_gold` uses a fixed seed, so runs are reproducible.
- **Caveat:** with a small gold set (12 queries), a 30% hold-out leaves ~8
  train queries — the loop has limited signal. The mechanism is correct; a
  larger gold set will make the hold-out gate more discriminating.
