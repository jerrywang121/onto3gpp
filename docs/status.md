# onto3gpp — Status Tracker

> **Purpose:** Live record of where we are, what's measured, and what's next.
> This is the persistent memory of project progress. Keep it concise.
> **Last updated:** 2026-08-24

## Current Stage

**Stage 0 — Baseline** (in progress)

## Stage Status

| Stage | Status | Branch | Metrics (MRR / NDCG@10 / Recall@10) | Notes |
|-------|--------|--------|-------------------------------------|-------|
| 0 Baseline | 🔵 in progress | `stage/0-baseline` | — | Project scaffolding done |
| 1 Terminology | ⚪ not started | — | — | |
| 2 Ontology | ⚪ not started | — | — | |
| 3 Intent | ⚪ not started | — | — | |
| 4 Improve loop | ⚪ not started | — | — | |
| 5 CPU NER | ⚪ not started | — | — | |

Legend: 🟢 done · 🔵 in progress · ⚪ not started · 🔴 blocked

## Recent Decisions (see `docs/adr/`)

- ADR-0001: AI-as-judge replaces human-in-the-loop.
- ADR-0002: Domain-general pipeline via domain packs.

## Open Questions / Next Actions

- [ ] Bootstrap gold set (`data/gold_queries.jsonl`).
- [ ] Implement document parser + BM25 baseline.
- [ ] Decide domain-pack schema (ADR-0003).

## Roll-back / Trial History

| Trial | Branch | Outcome | ADR |
|-------|--------|---------|-----|
| — | — | — | — |
