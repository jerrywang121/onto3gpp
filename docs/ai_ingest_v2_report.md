# AI Ingest v2 — Smoke Evaluation Report

**Date:** 2026-08-29  
**Prototype:** `prototypes/ai-ingest-v2/` (per-chunk extract → match → AI-merge, terms + relations)  
**Corpus:** TS 38.300 V18.3.0 (`38300-i30`), first **20 sections** (`--limit 20`), clean bootstrap (`--empty`)  
**Embed:** `embeddinggemma:300m` via Ollama `http://localhost:11434`, dim 768, `num_ctx 2048`, `keep_alive 30m`, threshold 0.25, top_k 5, batch 256  
**LLM (cmdc gateway `https://api.commandcode.ai/provider/v1`):** `extract=poolside/laguna-s-2.1-free` · `relations=poolside/laguna-s-2.1-free` · `merge=minimax/minimax-m3-free` (judge LLM on), temp 0.1/0.3/0.3, max_tokens 8000  
**Parallelism:** `--parallel 4` (one `ModelQueue` per task, maxsize 16)  
**Run:** `/tmp/v2/dict.json` + `/tmp/v2/ontology.json`, checkpointed via `dict.progress.jsonl` + per-chunk save, `--resume`

---

## 1. Ingest run summary

Two runs (sequential then parallel-resume) due to a gateway stall. Final artifact is the merged 20-chunk result.

| Run | Chunks | Mode | Outcome | Wall time |
|-----|--------|------|---------|-----------|
| 1 — `run.log` (unbuffered pipe, monitor via `progress.jsonl`) | 0–8 (9/20) | `--empty --limit 20` sequential | Stall on chunk 8 (`3.1 Abbreviations`, 7119 chars) — cmdc gateway 600 s default timeout per attempt, 5 attempts ≈ 2 min/chunk | — |
| 2 — `run2.log` PID 491809 | resume from 9/20 | `--resume --parallel 4` | Still stalled (LiteLLM footer spam 36 footers, no real exception text, progress frozen 9/20) | — |
| 3 — `run3.log` PID 493728 **(completed)** | resume from 9/20 → 20/20 | `--resume --parallel 4` **with `LLMClient._call` timeout fix** | `DONE: ok=10 fail=0 final_dict=438 final_concepts=438 final_relations=96 total_time=1448s` | 1448 s for the resumed 10 chunks (~145 s/chunk avg) |

**Gateway diagnosis.** The stall was not a crash — `queue.submit_json(...).result(timeout=90)` degraded to `[]` on exception, so chunks completed deterministically. Real root cause: cmdc calls via LiteLLM use `litellm.completion(model="openai/<model>", api_base=...)`; the `LLMClient._call` wiring was correct (maps `cmdc`→`openai` provider), and a tiny prompt succeeds. The slow model `poolside/laguna-s-2.1-free` takes ~45 s for an 800-char extraction prompt (vs 12 s for `minimax-m3-free`), and with no explicit `timeout` kwarg litellm defaults to **600 s** per attempt. Fix: `src/onto3gpp/llm/_core.py` now sets `"timeout": extra.get("timeout", 120)` — caps each attempt at 120 s and lets the ingest degrade fast instead of hanging minutes. After the fix `run3` completed 10 chunks with no stall; LiteLLM footers still appear (transient gateway errors) but are bounded.

**Per-chunk contribution** (from `dict.progress.jsonl`, `terms_step1={det,ai,union}`, `terms_added`/`terms_merged` after dedup+judge):

| idx | clause | det | ai | union | added | merged | rels_added | note |
|-----|--------|-----|----|-------|-------|--------|------------|------|
| 0 | *(empty)* | 5 | 0 | 5 | 5 | 0 | 0 | bootstrap |
| 1 | 650 | 33 | 1 | 34 | 32 | 2 | 5 |  |
| 2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | no terms |
| 3 | 2 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 4 | 3 | 0 | 11 | 11 | 11 | 0 | 2 | AI filled gap det missed |
| 5 | 1 | 3 | 8 | 8 | 6 | 2 | 3 |  |
| 6 | 2 | 48 | 12 | 60 | 49 | 11 | 4 |  |
| 7 | 3 | 0 | 0 | 0 | 0 | 0 | 0 |  |
| 8 | 3.1 Abbreviations | 234 | 9 | 237 | 214 | 23 | 1 | abbreviation list → 214 new terms |
| 9 | 3.2 | 73 | 14 | 85 | 27 | 58 | 23 | high merge rate (abbrev dedup) |
| 10 | 4 | 2 | 0 | 2 | 1 | 1 | 0 |  |
| 11 | 4.1 | 13 | 16 | 27 | 9 | 18 | 11 |  |
| 12 | 4.2 | 22 | 21 | 43 | 24 | 19 | 12 |  |
| 13 | 4.3 | 1 | 0 | 1 | 1 | 0 | 0 |  |
| 14 | 4.3.1 | 1 | 8 | 9 | 8 | 1 | 0 |  |
| 15 | 4.3.1.1 | 9 | 10 | 17 | 7 | 10 | 9 |  |
| 16 | 4.3.1.2 | 12 | 15 | 23 | 11 | 12 | 15 |  |
| 17 | 4.3.2 | 1 | 20 | 21 | 20 | 1 | 0 | AI-heavy |
| 18 | 4.3.2.1 | 7 | 10 | 16 | 3 | 13 | 2 |  |
| 19 | 4.3.2.2 | 8 | 18 | 24 | 10 | 14 | 9 |  |
| **TOTAL** |  | **—** | **173** | **—** | **438** | **185** | **96** | `ai_terms` counts AI candidates *before* dedup |

Takeaways: AI contributed **173 term candidates** before dedup (union counts deduplicate det+AI). Clause `3.1` alone contributed 214 terms (49% of the dict) — an abbreviation table the deterministic extractor already covers well (234 det). Later clauses show healthy **merge rates** (≈42% of inserts were judged as aliases/merges, 185/623), indicating the embedding+judge dedup is active.

---

## 2. Artifacts

| Artifact | AI v2 (20 sections) | Baseline `data/` (all 4 specs via deterministic pipeline) |
|----------|---------------------|-----------------------------------------------------------|
| `dict.json` entries | **438** | **5815** |
| `ontology.json` concepts | **438** | **5778** |
| `ontology.json` relations | **96** | **22719** |
| Validation errors | 0 | 0 |

Concept-type distribution (AI v2): `abbreviation 301` · `procedure 46` · `architecture 19` · `protocol 18` · `network_function 18` · `information_element 13` · `interface 7` · `phrase 6` · `qos 6` · `security 4` · …

Alias stats: avg 0.05 alias/concept, max 3, **422/438 concepts have 0 aliases** — the merge judge mostly mapped lexical variants (e.g. `3.2` merges 58) rather than creating abbreviation expansions. Overlap with baseline: **284/438 (64.8%)** canonicals already in the baseline dict; 154 AI-only canonicals are dominated by generic abbreviations surfaced from `3.1` (`TS`, `V18`, `TM`, `FRANCE`, `ETSI`, `UMTS`, `LTE`, `GSM`, `NAS`, `B`, …) — not discriminative for retrieval.

---

## 3. Evaluation — `evaluate_v2.py` harness (single-spec 38300 corpus, 60 gold queries)

Lab pairs (deterministic judges, `llm=False` — the harness default):

| Pairs | P | R | F1 | Acc | target_acc | retrieval@5 | Notes |
|-------|---|---|----|-----|------------|-------------|-------|
| term 18 (8 MERGE / 10 ADD) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | p50 ~700 ms/term |
| relation 12 (6 MERGE / 6 ADD) | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | 1.0 | p50 ~650 ms/term |
| **identical for baseline and AI artifacts** |  |  |  |  |  |  | Lab judges are deterministic; LLM judge path not exercised |

Corpus smoke (`data/parsed/38300-i30.jsonl` → 7463 chunks, scoped per-spec eval):

| Artifact | MRR | NDCG@10 | Recall@5 | Recall@10 |
|----------|-----|---------|----------|-----------|
| Baseline dict 5815 / onto 5778/22719 | **0.7185** | 0.7424 | 1.8194 | 2.9167 |
| **AI v2 dict 438 / onto 438/96** | **0.6767** | 0.7028 | 1.6694 | 2.5667 |
| **Delta (AI − baseline)** | **−0.0418** | −0.0396 | −0.1500 | −0.3500 |

---

## 4. Evaluation — `onto3gpp eval` CLI (multi-spec `data/parsed`, 60 gold queries, scoped per-spec BM25)

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Plain BM25 (no dict, no onto) | 0.5700 | 0.6246 | 1.2694 | 1.8417 |
| Term-expanded — baseline dict 5815 | 0.5971 | 0.6478 | 1.3194 | 2.1250 |
| Term-expanded — **AI dict 438** | 0.5700 | 0.6246 | 1.2694 | 1.8417 |
| **Full — baseline dict+onto** | **0.7185** | 0.7424 | 1.8194 | 2.9167 |
| **Full — AI dict+onto** | **0.6767** | 0.7028 | 1.6694 | 2.5667 |
| Delta full AI − full baseline | −0.0418 | −0.0396 | −0.1500 | −0.3500 |
| Delta full AI − plain | **+0.1067** | +0.0782 | +0.4000 | +0.7250 |

Interpretation:

- **AI dict alone adds zero lift** (0.5700 = plain). Its alias coverage is too thin (0.05/concept) and its 154 novel terms are not query-relevant, so `expand_query` has nothing to bridge.
- **AI ontology reranking does lift** plain BM25 by **+0.107 MRR** (0.5700 → 0.6767) and improves recall — related-concept boost surfaces sibling clauses. This confirms the `prototypes/ai-merge` finding that embedding+LLM merge improves dedup, and that even a sparse 96-relation graph helps ranking.
- **But AI full still trails the baseline full by 0.042 MRR.** Two compounding causes: (1) **coverage** — 438 concepts / 96 relations from 20 sections vs 5778/22719 from 4 specs; the gold set references clauses beyond the 20-section window and specs beyond 38300-i30. (2) **quality** — AI-only terms are generic abbreviations, not the discriminative multi-word phrases the deterministic extractor captures (see §2). A 4-spec AI run would narrow the gap but the quality signal suggests it would not close it without a prompt/filter change.
- **Fair 20-section deterministic baseline not yet isolated** — building a 20-section deterministic dict hit `CandidateTerm` vs `Dictionary.entries` shape mismatches in the ad-hoc script; the reported baseline (5815) is the 4-spec production dict. The per-chunk `det` counts show the deterministic extractor already finds 234 terms in `3.1` where AI adds only 9, so a 20-section deterministic dict would likely be ~300–350 terms, not 438 — AI's net *quantity* lift over deterministic on the same 20 sections is modest.

---

## 5. Comparison to prior AI-ingestion findings

| Experiment | Corpus | AI config | MRR vs verb baseline | Lesson |
|------------|--------|-----------|----------------------|--------|
| `ai_ingestion_report.md` — hybrid (base+AI) / AI-only (2026-08-25) | 329/532 of 38.300, local `deepseek`/`minimax` via Ollama | re-extract everything | −0.056 / −0.099 | Local models return generic concepts (`NR`, `5GC`, “AI”) — dilutes precision |
| `ai_ingestion_progressive_findings.md` — progressive gap-filling (2026-08-26) | 532 of 38.300, same local models | positive-context prompt + deterministic filter | **0.000** (neutral) | Gap-filling avoids large regression but still no lift |
| **This report — AI Ingest v2 smoke (2026-08-29)** | 20/532 of 38.300, **cmdc gateway** (`laguna-s-2.1` + `minimax-m3`) + `embeddinggemma:300m` | per-chunk extract→match→AI-merge, parallel 4 | **−0.042** (with 20-sec vs 4-spec caveat) | Gateway models are stronger than local Ollama but abbreviation-table terms are still non-discriminative; ontology reranking recovers +0.11 over plain |

Trend: **AI term extraction has not yet beaten the deterministic verb-based baseline on retrieval**, regardless of model tier. The `ai-merge` (embedding+LLM dedup) *does* help — the lab holds at 1.0 P/R/F1 and alias merges (185) are real — but the *extraction* step is the bottleneck.

---

## 6. Gate decision

**Do not promote** `/tmp/v2/dict.json` + `/tmp/v2/ontology.json` to `data/dict.json` + `data/ontology.json`.

Rationale: (1) retrieval regresses −0.042 MRR vs baseline (and would regress more if baseline were scoped to the same 20 sections, since AI dict alone shows no expansion lift); (2) 35% of AI terms are novel but non-discriminative; (3) the run covers only 20/532 sections of one spec — not a replacement for the 4-spec production artifacts. The `LLMClient` 120 s timeout fix is worth keeping (commit it), but the ingest output is not.

---

## 7. What to try next

1. **Prompt tuning** — the 800-char extract prompt returns bare abbreviations from `3.1`; add an instruction to skip single-token abbreviations already in the deterministic table and to prefer multi-word technical phrases (`NR-DC`, `Conditional Handover`, `SDT procedure over RACH`).
2. **Dictionary filter** — drop AI terms that are single uppercase tokens ≤3 chars or that match `/^[A-Z]{1,3}$/` unless they carry a definition sentence; this would cut the 301 `abbreviation` concepts that dominate the AI dict.
3. **Full-corpus replication** — rerun `--limit 0` (all 532 sections) with the timeout fix and the filter above, then re-evaluate scoped to 38300 vs 4-spec to isolate coverage from quality.
4. **Relation extraction** — 96 relations is sparse (0.22/concept vs 3.9 baseline). The per-chunk `rels_step1 det/ai/union` logging should be added to `progress.jsonl` to diagnose whether AI relations are being proposed and then filtered.
5. **Alias expansion** — wire `3.1` abbreviation definitions (`5GC — 5G Core`) into alias lists so `expand_query` can bridge `5GC`↔`5G Core` — the current 0.05 alias rate explains the zero expansion lift.

---

## 8. Repro

```bash
# Warm embed
curl -s http://localhost:11434/api/embed -d '{"model":"embeddinggemma:300m","input":"warm","options":{"num_ctx":2048},"keep_alive":"30m"}' >/dev/null

# Smoke (20 sections, clean)
.venv/bin/python -u prototypes/ai-ingest-v2/ingest_v2.py \
  --empty --limit 20 --parallel 4 \
  --parsed data/parsed/38300-i30.jsonl \
  --dict /tmp/v2/dict.json --ontology /tmp/v2/ontology.json \
  --base-dict data/dict.json --base-ontology data/ontology.json \
  --app-config config/app.yaml

# Full (all 532 sections, resume-safe)
.venv/bin/python -u prototypes/ai-ingest-v2/ingest_v2.py \
  --empty --parallel 4 \
  --parsed data/parsed/38300-i30.jsonl \
  --dict /tmp/v2_full/dict.json --ontology /tmp/v2_full/ontology.json \
  --base-dict data/dict.json --base-ontology data/ontology.json \
  --app-config config/app.yaml

# Eval (lab + corpus, single-spec)
.venv/bin/python prototypes/ai-ingest-v2/evaluate_v2.py \
  --dict /tmp/v2/dict.json --ontology /tmp/v2/ontology.json \
  --gold data/gold_queries_38300.jsonl --parsed data/parsed/38300-i30.jsonl

# Eval (CLI, multi-spec, 5 modes)
for m in plain "baseline expand" "baseline full" "AI dict-only" "AI full"; do
  .venv/bin/python -m onto3gpp.cli eval --parsed data/parsed --gold data/gold_queries_38300.jsonl \
    --expand data/dict.json --ontology data/ontology.json  # vary --expand/--ontology per mode
done
```

Artifacts: `/tmp/v2/dict.json` (438) · `/tmp/v2/ontology.json` (438/96) · `/tmp/v2/dict.progress.jsonl` (20 lines) · `/tmp/v2/run3.log` (DONE line + LiteLLM footers).
