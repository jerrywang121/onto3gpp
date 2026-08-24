# onto3gpp — Status Tracker

> **Purpose:** Live record of where we are, what's measured, and what's next.
> This is the persistent memory of project progress. Keep it concise.
> **Last updated:** 2026-08-24

## Current Stage

**Stage 1 — Terminology** (in progress)

## Stage Status

| Stage | Status | Branch | Metrics (MRR / NDCG@10 / Recall@10) | Notes |
|-------|--------|--------|-------------------------------------|-------|
| 0 Baseline | 🟢 done | `stage/0-baseline` | 1.000 / 0.992 / 1.000 | Synthetic sample; see caveat |
| 1 Terminology | 🔵 in progress | `stage/1-terminology` | 1.000 / 0.992 / 1.000 | Expansion mechanism works; no lift on synthetic sample |
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

## Stage 1 — Terminology (in progress)

**Delivered:**
- Candidate term extraction (rules-based): abbreviations + title phrases +
  paren-linked full names (`src/onto3gpp/extract/terms.py`).
- AI-as-judge gate (deterministic): support/accuracy/non-redundancy scoring,
  adaptive weighting for bootstrap vs. gold-evidence mode
  (`src/onto3gpp/judge.py`).
- Ontology compiler → Aho-Corasick dictionary (`src/onto3gpp/compile/dictionary.py`).
- Runtime NER (dictionary path) + query expansion (`src/onto3gpp/runtime/ner.py`).
- CLI: `onto3gpp build-dict`, `onto3gpp eval --expand`.
- 20 terms compiled from the synthetic sample.

**Metrics (synthetic sample):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Plain BM25 | 1.0000 | 0.9920 | 1.0000 | 1.0000 |
| Term-expanded | 1.0000 | 0.9920 | 1.0000 | 1.0000 |

> **Caveat:** the synthetic sample is too easy — plain BM25 is already
> perfect, so term expansion shows **no measurable lift** here. The expansion
> mechanism is proven correct by unit tests (abbreviation↔full-name
> resolution, alias→canonical mapping). A real lift requires real 3GPP
> documents where queries use abbreviations the docs spell out (or vice
> versa). **Stage gate not yet passed** — needs real docs to measure lift.

## Recent Decisions (see `docs/adr/`)

- ADR-0001: AI-as-judge replaces human-in-the-loop.
- ADR-0002: Domain-general pipeline via domain packs.
- ADR-0003: Compiled terminology dictionary (Aho-Corasick) for runtime NER.

## Open Questions / Next Actions

- [ ] Obtain real 3GPP documents to measure the term-expansion lift (Stage 1 gate).
- [ ] Stage 2: ontology + relations.
- [ ] Decide domain-pack schema (ADR-0003).

## Roll-back / Trial History

| Trial | Branch | Outcome | ADR |
|-------|--------|---------|-----|
| — | — | — | — |
