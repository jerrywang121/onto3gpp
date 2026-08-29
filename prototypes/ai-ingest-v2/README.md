# Prototype: AI Ingest v2 — per-chunk extract → match → AI-merge (terms + relations)

## Question

Can we replace the current batch ingestion (`extract all → align → merge`) with a **per-chunk, 4-step loop** that interleaves deterministic + AI extraction with retrieval + AI merge before updating the store, and apply it **symmetrically to terms and relations**?

User spec (2026-08-28):

> for each new chunk  
> step 1. ai extract terms + deterministic extract terms -> new terms  
> step 2. dict matching terms + semantic embedding matching terms (match terms found in step 1) -> existing terms  
> step 3. ai to merge terms from step 1 and 2, decide which terms are totally new, which terms to merge with existing terms  
> do the same 3 steps for relations  
> step 4. update dict and ontology then evaluate the performance

## Design

### Per-chunk loop (incremental index)

```
for chunk in sections (in order):
  # ── TERMS ─────────────────────────────────────────────
  1a. new_terms = DETECT_terms(chunk) ∪ AI_terms(chunk, llm.extract)
      dedup by canonical.lower(); keep highest confidence.
  2a. for each t in new_terms:
        dict_hits   = {c in onto | normalize(c)==normalize(t)}  (exact, threshold 1.0)
        embed_hits  = index.search_text(t.canonical, top_k, threshold)
        existing_candidates[t] = dict_hits ∪ embed_hits  (union, capped top_k+dict)
  3a. decisions_terms[t] = MergeJudge(t, existing_candidates[t])  (batch, LLM when enabled else deterministic)
      labels: ADD (new concept) | MERGE(target_id, reason)

  # ── RELATIONS ─────────────────────────────────────────
  1b. new_rels = DETECT_relations(chunk, onto ∪ new_terms) ∪ AI_relations(chunk, llm.relations)
      AI_relations sees chunk + known_rels + candidate_rels.
      dedup by (source,rel,target).
  2b. for each r in new_rels:
        # reuse term retrieval plus direct relation lookup
        dict_hits   = {existing rel | same (source,rel,target) after normalize+alias resolve}
        embed_hits  = rel_index.search_text(f"{r.source} {r.rel} {r.target}", top_k, threshold)
                      rel_index is over "source rel target" strings of existing relations
        existing_candidates[r] = dict_hits ∪ embed_hits
  3b. decisions_rels[r] = RelMergeJudge(r, existing_candidates[r])  LLM when enabled else deterministic alias-aware exact

  # ── UPDATE ────────────────────────────────────────────
  4. apply decided ADDs/MERGEs to Dictionary + Ontology + term_index + rel_index
     (aliases folded, indexes kept in sync for next chunk — incremental)
```

Why this shape:

* **Step 1 union** avoids LLM-only coverage gaps and keeps the reliable deterministic base (same lesson as ai_progressive: AI fills gaps, not replacement).
* **Step 2 hybrid retrieval** gives the judge a bounded, high-recall candidate set: cheap deterministic exact for the easy cases, embedding for hyphen/space/case/order variants that normalization alone misses (ADR-0014). Cost is O(k) per new term, not O(ontology).
* **Step 3 batch AI merge** is the only LLM gate — prompt sees `new term + top-k neighbours + cosine`, returns JSON `{decision,target,reason}`. Deterministic fallback is safe (no false merges on hard negatives).
* **Step 4 incremental** — later chunks see earlier decisions, so the store bootstraps progressively (same checkpoint/resume property as ai_progressive).

### Components reused

* `src/onto3gpp/extract/terms.py` + `src/onto3gpp/extract/relations.py` (deterministic)
* `src/onto3gpp/embed/embed.py` (`HashEmbedder` default, `TfIdfEmbedder`, `OllamaEmbedder`, `ApiEmbedder`, `EmbeddingIndex`, `get_embedder`) + `src/onto3gpp/ingest/merge_judge.py` (`MergeJudge`, `_normalize`, `_denied`) — already CPU-only, swappable local→API, LLM optional
* `src/onto3gpp/app_config.py` + `config/app.yaml` provider wiring (`COMMAND_CODE_API_KEY` etc.) and per-task `llm` routing (ADR-0015)
* Prompt templates from `prototypes/ai_ingest/ai_progressive.py` (`EXTRACT_PROMPT_TEMPLATE`, `RELATIONS_PROMPT_TEMPLATE`) — reliable single-field JSON format

### Relation handling (new)

Relations need their own index and judge because a relation is a triple, not a surface form. We embed the triple as a string `"source rel target"` and index existing relations the same way we index terms. Retrieval is `embed("source rel target") → top-k existing relation strings`. Judging is alias-aware exact when LLM disabled (same `source/target` canonicals after alias resolution → MERGE), otherwise a small LLM prompt analogous to the term judge but over relation triples. This keeps the relation path symmetric to the term path without inventing relation embeddings that require a separate model.

### Config

* `llm.extract` and `llm.relations` for step 1; `llm.merge` (shared with term merge judge) for steps 3a/3b — wired via `config/app.yaml` `providers` + `llm.models` (default `cmdc/minimax-m3-free`, overrides per task without repeating `api_key_env`).
* `embed` for both indexes (`kind: hash` default 384-d, `threshold: 0.25`, `top_k: 5`); swapping to `ollama`/`api` is a one-line `kind/provider` change. Same embedder instance backs both indexes.

### Evaluation plan

1. **Lab harness** (CPU-only, no LLM) — reuse `prototypes/ai-merge/evaluate.py` 18-pair term set plus a new 12-pair relation set (duplicate vs distinct triples). Metrics: P/R/F1, target accuracy, retrieval recall@k, p50 latency. Gate: no false merges on hard negatives (timers/DCI/opposites).
2. **Corpus smoke** — build ontology from a parsed sample (`data/parsed/38300-i30.jsonl`) with v2 vs v1 (deterministic) and compare: dict size, concept/relation counts, validation errors, duplicate rate, and retrieval metrics (MRR/NDCG/Recall) on `data/gold_queries_38300.jsonl`.
3. **With-LLM spot check** — when `llm.enabled`, verify LLM recovers hyphen misses that hash+deterministic misses (e.g. NG-AP/NGAP) without introducing false merges.

### Outcome / next steps

If lab + smoke show F1 ≥ 0.85 with zero false merges and no retrieval regression, promote `ingest_v2` into `src/onto3gpp/ingest/` (replacing the batch `pipeline.py` loop with the per-chunk loop) and record in ADR-0011/0014 + `docs/status.md`.
