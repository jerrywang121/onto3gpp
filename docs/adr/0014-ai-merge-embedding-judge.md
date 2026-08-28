# ADR-0014: Embedding + AI Merge Judge for ABox Deduplication

- **Status:** Accepted
- **Date:** 2026-08-28
- **Stage:** 9 (AI-assisted knowledge ingestion) — promotion of `prototypes/ai-merge`
- **Related:** ADR-0005, ADR-0011, ADR-0012, ADR-0013

## Context

During ingestion, newly extracted terms must be decided as **ADD** (new concept) vs **MERGE** (alias of an existing concept). The deterministic `merge_abox` does case-insensitive canonical matching only. Prior prototypes showed:

- `prototypes/consolidation`: Dice-bigram fuzzy merge is **unsafe** for 3GPP — single-character flips change meaning (`ACTIVE`/`INACTIVE` 0.86, `T3444`/`T3445`, `C1-174182`/`C1-174183`), `DCI-1-0`/`DCI-0-1` must not merge. The only safe auto-merge was normalized exact (`casefold` + hyphen→space + sorted tokens) plus a denylist.
- `prototypes/ai-merge`: adding an embedding retrieval layer before the judge lets the LLM see only top-k neighbours (bounded cost) and recover hyphen/case/order variants (`NGAP`/`NG-AP`, `E-UTRAN`/`EUTRAN`, `NRDC`/`NR-DC`) that normalization alone misses.

We need a **pluggable, CPU-only default** embedding plus a **swappable API** path, and an **LLM judge that is optional** (deterministic fallback is the default, safe path).

## Decision

1. Add `src/onto3gpp/embed/` — `Embedder` protocol (`dim`, `embed(texts) -> vectors` L2-normed) with:
   - `HashEmbedder` (default, 384-d, char 3–5-grams over `" "+norm+" "`, `w:tok`/`bw:bigram`, signed second hash, stdlib only) — captures lexical variants without a model download.
   - `TfIdfEmbedder` (corpus-weighted variant, same bucketing, IDF `log((N+1)/(df+1))+1`).
   - `OllamaEmbedder` (POST `http://localhost:11434/api/embed` `{"model","input"}` then fallback `/v1/embeddings`, e.g. `embeddinggemma:300m` 768-d).
   - `ApiEmbedder` (POST `api_base/embeddings` OpenAI-compat, `api_key` via config/env).
   - `EmbeddingIndex` (brute cosine, L2-normalized dot, replaceable with FAISS) and `get_embedder(cfg)` factory (`cfg.kind` = `hash|tfidf|ollama|api`).

2. Add `src/onto3gpp/ingest/merge_judge.py` — `_normalize`/`_denied`/`MergeJudge`/`decide`:
   - Deterministic: MERGE iff normalized canonicals equal and not in `DCI-1-0`/`DCI-0-1` denylist.
   - LLM (when `LLMClient(enabled=True)`): prompt with new term + neighbours (id/canonical/type/cosine), JSON `{decision,target,reason}`; hallucinated target not in neighbours → ADD; errors fall back to deterministic.
   - Prompt explicitly says timers/DCI/identifiers single-char distinct, hyphen/space/case same.

3. Extend `src/onto3gpp/ingest/merge.py` with `merge_abox_with_judge(existing, incoming, *, index, judge, threshold=0.25, top_k=5)` — exact `casefold` key first (free), else embed→threshold→judge; on MERGE fold canonical into target aliases, on ADD insert and keep index in sync.

4. Domain-pack `embed:` block (`kind`, `dim`, `api_base`, `model`, `api_key`, `threshold`, `top_k`; defaults `hash/384/0.25/5`) via `DomainConfig.embed` (`src/onto3gpp/config.py`). Template + `3gpp` packs document ollama/api examples. Secrets stay local-only.

## Alternatives considered

- Dice/TF-IDF fuzzy threshold without judge — rejected (consolidation shows it merges distinct identifiers).
- LLM over full ontology — rejected (unbounded cost; retrieval bounds prompt to top-k).
- API-only embedding — rejected (offline/air-gapped use requires a local default; hash is instant, no download).

## Consequences

- Ingest can call `merge_abox_with_judge` when `embed`/`llm.merge` configured; otherwise stays deterministic (no behaviour change, no new deps, no secrets).
- Measured on `prototypes/ai-merge/evaluate.py` 18-pair holdout (8 MERGE, 10 ADD incl. hard negatives):
  - hash deterministic: P/R/F1 1.0/0.625/0.77, retrieval@5 0.625, p50 <1 ms — **no false merges**.
  - hash + LLM: 1.0/0.75/0.86 (LLM recovers some hyphen misses when retrieval passes threshold).
  - ollama (`embeddinggemma:300m`) + LLM: **1.0/1.0/1.0** (LLM recovers all 3 hyphen-concatenated misses).
- Local hash is lexical; semantic merges beyond hyphen/space/case need the API/Ollama path or LLM over aliases.

## Verification

- `tests/test_embed.py` (hash determinism, hyphen variants, TfIdf, index, factory)
- `tests/test_merge_judge.py` (normalize, denylist, deterministic MERGE/ADD, threshold, hallucinated-id fallback, disabled-LLM fallback)
- `tests/test_config_embed.py` (`embed:` defaults + parsing)
- `tests/test_ingest_merge.py` still green
