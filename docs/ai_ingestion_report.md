# AI-Assisted Ingestion vs. Verb-Based Extraction — Evaluation Report

**Date:** 2026-08-25
**Spec:** 3GPP TS 38.300 (i30), 532 parsed sections
**Gold set:** `data/gold_queries_38300.jsonl` (12 queries)
**Models:** `deepseek-v4-flash:0731-cloud` (extract), `minimax-m3:cloud` (judge) — local Ollama @ `http://localhost:11434`

---

## 1. Objective

The user asked to run AI-assisted ingestion on the parsed corpus, generate a new
dictionary + ontology, and evaluate whether AI-assisted extraction improves
retrieval over the existing **deterministic verb-based** extraction.

## 2. Method

Three ingestion variants were built and evaluated against the same gold set:

1. **Baseline (verb-based)** — the existing deterministic pipeline
   (`data/dict.json` + `data/ontology.json`): 5,815 dict entries, 5,778 concepts.
2. **Hybrid** — deterministic base **plus** AI-extracted concepts layered on top:
   6,728 dict entries (base 5,815 + AI 913), 6,709 concepts.
3. **AI-only** — concepts extracted purely by the LLM: 1,179 entries, 1,179 concepts.

AI extraction ran over **329 of 532 sections** (62%) before being stopped once the
trend was clear. It produced 1,904 raw concepts → 1,179 unique. The extraction was
checkpointed/resumable and used a retry wrapper (`complete_json`) to handle the
models' frequent empty/malformed JSON responses.

All variants were evaluated with the same command:

```
onto3gpp eval --parsed data/parsed --gold data/gold_queries_38300.jsonl \
  --expand <dict> --ontology <ontology>
```

## 3. Results

| Variant | MRR | NDCG@10 | Recall@5 | Recall@10 |
|---|---|---|---|---|
| **Baseline (verb-based)** | **0.6369** | **0.6699** | **1.5833** | **2.3333** |
| Hybrid (base + AI) | 0.5813 | 0.6022 | 1.5000 | 2.0000 |
| AI-only | 0.5382 | 0.5594 | 1.3333 | 1.7500 |

*(Plain BM25, no expansion: MRR 0.6146 — included for reference.)*

## 4. Findings

### 4.1 AI-assisted extraction **degrades** retrieval on this setup

- **Hybrid** loses **0.056 MRR** vs. baseline (0.5813 vs 0.6369).
- **AI-only** loses **0.099 MRR** (0.5382) — and is far sparser (1,179 vs 5,815
  entries), so it cannot stand alone.
- Adding AI concepts to the dictionary expands queries with **irrelevant terms**,
  dragging down ranking precision.

### 4.2 Why the AI layer hurts

The local Ollama models return **generic, low-value concepts** that are too broad
to discriminate between clauses:

- `NR`, `5GC`, `NG-RAN`, `E-UTRAN` typed as `architecture`/`network_function`
- `Artificial Intelligence`, `Augmented Reality`, `Backhaul`, `Air to Ground`

These are real 3GPP terms but are **not clause-discriminative** — they match many
sections, so expanding queries with them dilutes precision rather than sharpening
recall.

### 4.3 Model reliability is poor

- The "extract concepts from text" prompt worked **~97%** of the time (319/329 ok),
  but the models are **slow** (~0.08 sections/s → ~12s/section) and
  **nondeterministic** — occasionally returning empty or malformed JSON.
- A "retype existing terms" prompt format **failed 100%** across both models
  (all 10 retry attempts returned empty) and was abandoned.
- The verbose `extract_terms.txt` template also fails with local models.

## 5. Conclusion

On this local-model setup, **AI-assisted ingestion does not improve retrieval**
over the deterministic verb-based baseline. The verb-based extractor already
captures the discriminative terms; the LLM adds generic noise.

This is a **valid, evidence-backed negative result** — and it aligns with the
project's philosophy (ADR-0011): the **AI-as-judge** gate would reject these
low-confidence, non-discriminative candidates before they enter the ontology.
The deterministic-first pipeline is the right default; AI should **fill gaps the
deterministic extractor misses**, not re-extract everything.

## 6. Recommendations

1. **Do not promote** the AI-extracted dict/ontology to `main` — it regresses MRR.
2. **Reframe the AI role**: use AI to *retype/refine* existing deterministic
   candidates (which failed with local models) or to *fill specific gaps* (terms
   the verb-based extractor misses), gated by the judge — not to re-extract.
3. **If pursuing AI extraction**, use a stronger/remote model and a
   confidence threshold to filter generic concepts before they enter the dict.
4. **Keep the deterministic pipeline as the runtime default** — it is cheaper,
   deterministic, and higher-performing on this eval.

## 7. Artifacts

| Artifact | Path |
|---|---|
| AI extraction output (checkpointed) | `/tmp/ai_full.jsonl` |
| Hybrid dict | `/tmp/hybrid_dict_full.json` |
| Hybrid ontology | `/tmp/hybrid_onto_full.json` |
| AI-only dict | `/tmp/ai_only_dict_full.json` |
| AI-only ontology | `/tmp/ai_only_onto_full.json` |
| Extraction helpers | `prototypes/ai_ingest/ai_helpers.py` |
| Extraction script | `prototypes/ai_ingest/ai_extract.py` |
| Hybrid builder | `prototypes/ai_ingest/ai_hybrid.py` |
| AI-only builder | `prototypes/ai_ingest/ai_build.py` |

---

## 8. Follow-up: Progressive AI-assisted extraction (2026-08-25)

The negative result above led to a **reframed strategy** (ADR-0011): instead of
asking the AI to re-extract everything from scratch, use it to **fill gaps the
deterministic extractor misses**, feeding the current dict/ontology as context.

### 8.1 Design (`prototypes/ai_ingest/ai_progressive.py`)

For each input chunk (section), the pipeline runs a/b/c/d:

- **(a) Deterministic extraction** → candidate terms + relations
  (`extract_candidates`, `extract_relations`).
- **(b) Match the chunk against the CURRENT dict + ontology** → known terms
  (`d.find`) and known relations (those touching a known term).
- **(c) AI decides what to ADD** — given the chunk + the deterministic
  candidates + the known terms as **positive reference context**, the model
  lists NEW concepts the deterministic extractor missed.
- **(d) Deterministic filter + apply** — only concepts **not already in** the
  dict/ontology are added (`apply_result`); relations are re-extracted
  deterministically over the updated ontology (the reliable path).

The dict + ontology are updated **incrementally**, so later chunks see the
accumulated knowledge (**progressive bootstrapping**). The run is
**checkpointed + resumable**: dict/ontology are written to disk after each
chunk, and a `.progress.jsonl` log records per-chunk additions.

### 8.2 Prompt design (reliability lesson)

The local Ollama models return **empty** when given an exclusion list
("do NOT re-add these"). The reliable format is a **plain "extract concepts"**
prompt. So the prompt feeds the deterministic candidates + known terms as
**positive reference context** and asks for NEW concepts; already-known
concepts are still filtered out **deterministically** in `apply_result` as a
safety net. This gives the "AI fills gaps" behavior without relying on the
flaky model to respect an exclusion list.

### 8.3 Monitoring (match-size + per-query additions)

Because the dict/ontology grow as the run progresses, the context fed to the AI
grows too. To detect this, each chunk's result records a `_match` metadata
block:

```json
{"clause": "4.3.1.1", "terms_added": 8, "relations_added": 1,
 "match": {"known_terms": 17, "known_relations": 0, "candidates": 9},
 "result": {"concepts": [...]}}
```

- `match.known_terms` / `match.known_relations` — how many terms/relations the
  **current** dict/ontology matched in this chunk (grows as the KB expands).
- `match.candidates` — deterministic candidates found in this chunk.
- `terms_added` / `relations_added` — new entries added by this chunk.

The CLI also prints running totals (`match_terms`, `match_rels`,
`match_cands`) every 10 chunks, so we can see whether the context size and the
per-query addition rate grow over the run.

### 8.4 Status

A 20-section smoke test confirmed the monitoring works (progress log shows
`match` metadata + per-chunk additions). The full 532-section run is in
progress; eval results vs. the verb-based baseline (MRR 0.6369) will be
appended here when complete.

**20-section smoke test (2026-08-25):**

| Metric | Value |
|---|---|
| Sections processed | 20 |
| OK / failed | 15 / 5 |
| Terms added | 22 |
| Relations added | 3 |
| Final dict / concepts | 5,826 / 5,789 |
| Rate | ~0.04 sections/s (~25s/section) |

- **Monitoring confirmed working:** each chunk logged `match.known_terms`,
  `match.known_relations`, `match.candidates` plus `terms_added` /
  `relations_added`. Running totals printed every 10 chunks.
- **25% failure rate (5/20):** the model returned empty across all 10 retries
  on 5 sections (`all 10 attempts failed: None`). This is the known local-model
  flakiness; failed sections are skipped and the run continues (checkpointed).
- **Match sizes grow with the KB:** `known_terms` ranged 0→53 across chunks,
  confirming the context fed to the AI grows as the dict/ontology expand — the
  exact growth the monitoring was designed to track.
