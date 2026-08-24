# onto3gpp — Status Tracker

> **Purpose:** Live record of where we are, what's measured, and what's next.
> This is the persistent memory of project progress. Keep it concise.
> **Last updated:** 2026-08-24

## Current Stage

**Stage 1 — Terminology** (next up)

## Stage Status

| Stage | Status | Branch | Metrics (MRR / NDCG@10 / Recall@10) | Notes |
|-------|--------|--------|-------------------------------------|-------|
| 0 Baseline | 🟢 done | `stage/0-baseline` | 1.000 / 0.992 / 1.000 | Synthetic sample; see caveat |
| 1 Terminology | ⚪ not started | — | — | |
| 2 Ontology | ⚪ not started | — | — | |
| 3 Intent | ⚪ not started | — | — | |
| 4 Improve loop | ⚪ not started | — | — | |
| 5 CPU NER | ⚪ not started | — | — | |

Legend: 🟢 done · 🔵 in progress · ⚪ not started · 🔴 blocked

## Stage 0 — Baseline (done)

**Delivered:**
- Document parser (text → clause-structured sections).
- Chunker with section metadata.
- BM25 index + search.
- Eval harness (MRR, NDCG@10, Recall@5/10).
- Gold set bootstrap (`data/gold_queries.jsonl`, 10 queries).
- CLI: `onto3gpp parse`, `onto3gpp eval`.

**Metrics (synthetic sample `data/sample/23.501.txt`):**

| Metric | Value |
|--------|-------|
| MRR | 1.0000 |
| NDCG@10 | 0.9920 |
| Recall@5 | 1.0000 |
| Recall@10 | 1.0000 |

> **Caveat:** these metrics are on a tiny synthetic sample and are
> near-perfect. They establish the *harness works*, not real-world quality.
> Real 3GPP documents + a larger gold set are needed for meaningful baselines.

## Recent Decisions (see `docs/adr/`)

- ADR-0001: AI-as-judge replaces human-in-the-loop.
- ADR-0002: Domain-general pipeline via domain packs.

## Open Questions / Next Actions

- [ ] Stage 1: candidate term extraction + compiled dictionary.
- [ ] Obtain real 3GPP documents for a meaningful baseline.
- [ ] Decide domain-pack schema (ADR-0003).

## Roll-back / Trial History

| Trial | Branch | Outcome | ADR |
|-------|--------|---------|-----|
| — | — | — | — |
