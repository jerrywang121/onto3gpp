# ADR-0001: AI-as-Judge Replaces Human-in-the-Loop

- **Status:** Accepted
- **Date:** 2026-08-24
- **Related:** ADR-0002

## Context

The original brainstorm (`docs/brainstorm/implementation.md`) had a "Human
Review Gate" in the offline pipeline and a human-gated recursive improvement
loop. The user explicitly wants to **remove the human from the loop**, using AI
as judge for initial bootstrap and iterative update/improvement.

The risk: AI judging its own output can be self-referential and hallucinate
confidently. We need a gate that is auditable and grounded.

## Decision

Replace the human review gate with an **AI-as-Judge** gate that scores
candidates against a **ground-truth gold set** with standard IR metrics
(MRR, NDCG@k, Recall@k) plus provenance checks.

- **Bootstrap:** AI extracts candidate terms/relations, then judges its own
  output against the gold set + provenance. Only candidates passing the
  confidence threshold enter the ontology.
- **Iterative improvement:** AI analyzes search logs, proposes changes, judges
  them against a **hold-out eval set**, and promotes only if metrics improve.
- **Humans set policy** (thresholds, gold set, domain pack) but do **not**
  review every candidate.

## Options Considered

- **Option A — Human review gate (original):** safest but slow, doesn't scale,
  contradicts the user's requirement.
- **Option B — AI-as-judge against gold set (chosen):** removes human, grounded
  in metrics, auditable.
- **Option C — No gate:** fastest but unsafe (hallucinations contaminate the
  ontology).

## Rationale

The judge is not free-form opinion — it is scored against a ground-truth gold
set. A wrong candidate that degrades metrics is rejected by the loop itself.
This satisfies the user's requirement while keeping the system auditable.

## Consequences

- **Open questions to resolve (prototype/ADR):**
  - How to calibrate the judge's confidence threshold?
  - How to prevent self-referentiality (judge approving its own hallucinations)?
  - Minimum gold-set size for reliable gating?
- **Roll-back path:** if the AI-as-judge gate proves unreliable, we can fall
  back to a lightweight human review of only high-impact candidates (a hybrid),
  or add a second independent judge model.
