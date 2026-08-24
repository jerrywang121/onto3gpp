# onto3gpp — Status Tracker

> **Purpose:** Live record of where we are, what's measured, and what's next.
> This is the persistent memory of project progress. Keep it concise.
> **Last updated:** 2026-08-24

## Current Stage

**Stage 2 — Ontology + Relations** (in progress)

## Stage Status

| Stage | Status | Branch | Metrics (MRR / NDCG@10 / Recall@10) | Notes |
|-------|--------|--------|-------------------------------------|-------|
| 0 Baseline | 🟢 done | `stage/0-baseline` | 1.000 / 0.992 / 1.000 | Synthetic sample; see caveat |
| 1 Terminology | 🔵 in progress | `stage/1-terminology` | 0.484 / 0.568 / 0.778 | Real gold set; term-expansion regresses vs plain |
| 2 Ontology | 🔵 in progress | `stage/2-ontology` | 0.628 / 0.679 / 0.833 | Reasoner + reranker done; Recall@5 lift confirmed |
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

## Stage 2 — Ontology + Relations (in progress)

**Delivered:**
- Concept/relation schema + validation + merge + serialization
  (`src/onto3gpp/ontology/schema.py`).
- Rules-based relation extraction with word-boundary matching
  (`src/onto3gpp/extract/relations.py`).
- Ontology reasoner → query IR (primary + related terms, hub-capped)
  (`src/onto3gpp/runtime/reasoner.py`).
- Relationship-aware reranker (ontology-aware candidate generation +
  related-concept boost) (`src/onto3gpp/runtime/reranker.py`).
- CLI: `onto3gpp build-ontology`, `onto3gpp eval --ontology`.
- Real 3GPP spec (TS 38.300 V18.3.0) parsed → 532 sections, 911-term
  dictionary, 879-concept / 2027-relation ontology.
- Real gold set (`data/gold_queries_38300.jsonl`, 12 queries referencing
  real 38.300 clauses).

**Metrics (real TS 38.300, `data/gold_queries_38300.jsonl`):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Plain BM25 | 0.6250 | 0.6765 | 0.7500 | 0.8333 |
| Term-expanded | 0.4841 | 0.5684 | 0.6111 | 0.7778 |
| Ontology-aware | 0.6278 | 0.6791 | 0.8333 | 0.8333 |

> **Findings:**
> - Ontology-aware reranking gives a **modest lift** over plain BM25 on MRR
>   (0.6278 vs 0.6250) and a **clear lift on Recall@5** (0.8333 vs 0.7500) —
>   it surfaces related-concept chunks that share no exact tokens with the
>   query.
> - Term-expanded (Stage 1) is *worse* than plain BM25 on this gold set. The
>   expansion adds canonical surface forms that dilute the query signal. This
>   needs investigation — likely the dictionary's canonical forms are too
>   generic (e.g. "UE", "RRC") and add noise rather than disambiguation.
> - The ontology has noisy hub concepts (UE degree 457, OF/AND/AS stopwords).
>   The reasoner caps related-term expansion per concept and filters
>   stopwords/single-char noise; the reranker uses a small boost (0.2) so exact
>   token matches still win.

**Pending:**
- Investigate term-expansion regression (Stage 1 gate).
- Stage gate: relationship-aware ranking lift vs. Stage 1 — **partially met**
  (Recall@5 lift confirmed; MRR lift marginal).

## Open Questions / Next Actions

- [ ] Investigate why term-expanded search underperforms plain BM25 on the
      real gold set (Stage 1 gate).
- [ ] Consider pruning noisy hub concepts / stopwords from the ontology at
      build time (not just at reason time).
- [ ] Decide domain-pack schema (ADR-0003).

## Roll-back / Trial History

| Trial | Branch | Outcome | ADR |
|-------|--------|---------|-----|
| — | — | — | — |
