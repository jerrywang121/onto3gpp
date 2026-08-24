# ADR-0006: Structure-Aware Ranking Boost (additive, proportional)

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 3 (Intent + Structure Boosts)

## Context

BM25 ranks chunks by lexical overlap between query and chunk *body text*. But
3GPP specs are clause-structured: a clause's **title** (and its ancestor
titles) is a strong relevance signal even when the body text shares no query
tokens. E.g. the query "How is small data transmission supported over RACH?"
should surface clause 18.1 "Support of SDT procedure over RACH" even though
its body text doesn't contain the exact query tokens. We need a deterministic,
CPU-only structure-aware boost.

## Decision

Add a structure boost to candidate scoring in `search_structure`:

- For each clause, compute the set of tokens in its title **plus** all
  ancestor-clause titles (via `build_ancestor_map`).
- `overlap = |query_tokens ∩ title_tokens|`.
- `frac = overlap / max_overlap` (normalized to the best structure match).
- `structure_boost = max_bm25_score * frac * 0.4`.
- Final score = `bm25_score + structure_boost` (**additive**).

## Alternatives considered

1. **Floor score for title-matching chunks** (score = `max_score * frac` only
   when BM25 score == 0). Rejected: clauses with a *partial* BM25 score (e.g.
   18.1 at 9.03) stayed buried below unrelated high-scoring chunks. Only
   score==0 chunks benefited, so the SDT query still missed.
2. **Boost factor 0.5.** Rejected: over-promoted sub-clauses. The QoE query
   regressed (MRR 1.00 → 0.25) because 21.2.2 "QoE Measurement Collection
   Deactivation" matched 3 title tokens vs. gold 21.1 "Overview" matching 2.
3. **Boost factor 0.3.** Rejected: under-promoted. The handover query dropped
   to MRR 0.25 (16.15.5 "Non-Homogeneous support..." rose above the gold
   children).

## Consequences

- **Measured lift** (real TS 38.300 gold set): MRR 0.7861 → 0.8542, NDCG
  0.8158 → 0.8954, Recall@5 0.8333 → 0.9444, Recall@10 0.9167 → 0.9722.
- The boost is **proportional to overlap count**, so a specific match (many
  shared title tokens) ranks above a generic one (a single shared token like
  "RRC").
- The 0.4 factor is a **gentle nudge**: it lifts a clause with a partial BM25
  score above unrelated high-scoring chunks without overriding close BM25
  scores between siblings.
- **Known limitation:** a clause with empty body text (textlen=0) is skipped
  by the chunker and can never be retrieved, even if its title matches. This
  is a data/chunker issue, not a ranking issue (see status.md Stage 3).
