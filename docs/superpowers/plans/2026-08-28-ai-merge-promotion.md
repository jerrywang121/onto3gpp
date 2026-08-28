# Embedding + AI Judge Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the ai-merge prototype (swappable CPU embedding + cosine index + LLM merge judge) into the main app so `ingest` can deduplicate near-duplicate terms (hyphen/case/order variants) via embedding retrieval + an optional LLM judge, keeping the deterministic path as the default and preserving safety (no false merges on DCI-1-0/DCI-0-1 etc.).

**Architecture:** New module `src/onto3gpp/embed/` holds pluggable embedders (Hash/TfIdf default-CPU, Ollama local, OpenAI-compatible API) and `EmbeddingIndex` (brute cosine, replaceable with FAISS). Merge layer `src/onto3gpp/ingest/merge.py` gains `merge_abox_with_judge` / `decide_merge` that does embed→top-k→judge (LLM when enabled, normalized+denylist fallback otherwise). Config surface is `domain/config.yaml` `embed:` block + existing `llm.merge`. Prototype stays as reference but main code is the supported path.

**Tech Stack:** Python 3.11, stdlib-only local embeddings (`hashlib`, `math`, `urllib`), `litellm` already in deps for LLM, `pytest`, `yaml`, `src/onto3gpp/llm.py` (`LLMClient`/`LLMConfig`), `src/onto3gpp/ontology/abox.py`.

## Global Constraints

- Python >= 3.11 (per pyproject.toml)
- Deterministic runtime is AI-free by default; embedding/judge are **offline ingest** only (AGENTS.md §0)
- No secrets in repo: `api_key`/`api_base` stay local-only; `docs/domain/3gpp/config.yaml` keeps provider=ollama default, not cmdc + hard key
- TDD required for feature work (AGENTS.md §2)
- Evidence before assertions; small reversible commits
- CPU-only local path must have no extra heavy deps (hash embedder stays stdlib)

---

### Task 1: Embed module — Hash/TfIdf/Ollama/Api + index + factory

**Files:**
- Create: `src/onto3gpp/embed/__init__.py`
- Create: `src/onto3gpp/embed/embed.py`
- Test: `tests/test_embed.py`

**Interfaces:**
- Consumes: stdlib only for Hash/TfIdf; optional live Ollama at http://localhost:11434 for integration check (not required in CI)
- Produces: `Embedder` Protocol (`dim: int`, `embed(texts: list[str]) -> list[list[float]]`); `HashEmbedder(dim=384)`, `TfIdfEmbedder(dim, corpus)`, `OllamaEmbedder(api_base, model, dim, timeout)`, `ApiEmbedder(api_base, model, api_key, dim, timeout)`; `EmbeddingIndex(dim, embedder)` with `add/ add_many/ search/ search_text` (cosine, L2-normed); `get_embedder(cfg: dict) -> Embedder` with `cfg={"kind": "hash"|"tfidf"|"ollama"|"api", ...}`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embed.py
from onto3gpp.embed import HashEmbedder, TfIdfEmbedder, get_embedder, EmbeddingIndex

def test_hash_deterministic_and_normed(): ...
def test_hash_hyphen_variants_close(): # NGAP vs NG-AP closer than NGAP vs UPF
def test_hash_alias_vs_canonical(): ...
def test_tfidf_without_corpus_matches_hash(): ...
def test_tfidf_fit_changes_weights(): ...
def test_index_add_and_search_returns_topk_sorted(): ...
def test_index_search_text_consistent_with_search(): ...
def test_get_embedder_factory_kinds(): # hash, tfidf pass; api/ollama smoke without network
def test_embed_empty_text_zero_vec(): ...
```

Run: `pytest tests/test_embed.py -v`

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_embed.py -v`
Expected: FAIL (module not found / not implemented)

- [ ] **Step 3: Implement minimal embed module**
Copy/adapt `prototypes/ai-merge/embed.py` into `src/onto3gpp/embed/embed.py` + re-export in `__init__.py`. Keep hash logic: lower + "-"/"_"→space, char 3-5grams over " "+t_norm+" ", word tokens `w:tok` + bigrams `bw:`, dual hash (md5 + signed second hash), L2. TfIdf: fit(df→idf log((N+1)/(df+1))+1), scale. Ollama: POST /api/embed then fallback /v1/embeddings (urllib, 15s timeout). Api: POST /v1/embeddings (urllib, 30s). L2-normalize outputs. Index: brute cosine over dict, L2-normalize query vec internally.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_embed.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
`feat(embed): pluggable CPU embedding (hash/tf-idf/ollama/api) + cosine index`

---

### Task 2: Merge judge — deterministic+LLM decide vs denylist

**Files:**
- Create: `src/onto3gpp/ingest/merge_judge.py` (or extend `merge.py` — prefer new file, re-export from merge.py)
- Modify: `src/onto3gpp/ingest/merge.py` — add `merge_abox_with_judge` / `decide_merge` wiring; keep `merge_abox` backward-compat
- Test: `tests/test_merge_judge.py`

**Interfaces:**
- Consumes: `EmbeddingIndex` from Task 1; `LLMClient`/`LLMConfig` from `src/onto3gpp/llm.py` (optional; disabled by default)
- Produces: `_normalize`, `_denied`, `MergeDecision(decision: MERGE|ADD, target, reason, neighbours, used_llm)`, `MergeJudge(llm_client, model_name).judge(new_canonical, new_type, neighbours) -> dict`, `decide_merge/new_canonical,... threshold=0.25, top_k=5, id_to_canonical, id_to_type, index, judge) -> MergeDecision`, `merge_abox_with_judge(existing, incoming, *, index, judge, threshold, top_k) -> MergeResult` (or annotate MergeResult with merge decisions while keeping stats)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_merge_judge.py
from onto3gpp.ingest.merge_judge import _normalize, _denied, MergeJudge, decide_merge

def test_normalize_sorted_tokens_and_collapse(): ...
def test_denied_dci_variants_not_merged(): # dci-1-0 vs dci-0-1 is ADD
def test_judge_deterministic_merges_when_normalized(): # ngap vs NG-AP -> MERGE
def test_judge_deterministic_add_when_distinct(): # ACTIVE vs INACTIVE -> ADD
def test_judge_no_neighbours_is_add(): ...
def test_decide_merge_respects_threshold(): ...
def test_merge_abox_with_judge_alias_merges(): ...
def test_llm_hallucinated_id_falls_back_to_add(monkeypatch): # fake LLM returning target not in neighbours
def test_llm_disabled_path_uses_deterministic(): ...
```

Run: `pytest tests/test_merge_judge.py -v`

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_merge_judge.py -v`
Expected: FAIL

- [ ] **Step 3: Implement minimal judge**
Port `prototypes/ai-merge/merge.py` into `src/onto3gpp/ingest/merge_judge.py`. Prompt: "3GPP ontology merge judge… timers/DCI/identifiers single-char distinct, hyphen/space/case SAME" + neighbours list (id/canonical/type/cosine) → JSON {decision,target,reason}. Hallucinated target not in neighbours → ADD. Missing LLM / disabled → normalized match + denylist. `LLMClient` may be None. `decide_merge`: embed+search index.search_text → filter by threshold → judge.judge → MergeDecision. `merge_abox_with_judge`: build canonical-key dedupe + embedding+judge per incoming concept; on MERGE merge aliases into target id, else add; relations same as before.

- [ ] **Step 4: Run test to verify it passes**
Run: `pytest tests/test_merge_judge.py -v`  and `pytest tests/test_ingest_merge.py -v` (keep green)
Expected: PASS

- [ ] **Step 5: Commit**
`feat(ingest): LLM merge judge + embedding-guided ABox merge (deterministic fallback, DCI denylist)`

---

### Task 3: Config + domain-pack wiring

**Files:**
- Modify: `src/onto3gpp/config.py` — add `embed` config parsing (optional, defaults to hash)
- Modify: `docs/domain/_template/config.yaml` — document `embed:` block
- Modify: `docs/domain/3gpp/config.yaml` — add `embed:` (default hash, commented ollama/api examples); keep llm.merge already present
- Test: `tests/test_llm_routing.py` (extend) + `tests/test_config.py` or inline in `test_llm_rate_limits` pattern

**Interfaces:**
- Consumes: `yaml` domain pack; `LLMConfig` routing already tested
- Produces: `DomainConfig.embed` (dataclass or dict) with `{kind, dim, api_base, model, api_key, threshold, top_k}` defaults `{kind:"hash", dim:384, threshold:0.25, top_k:5}`; loader preserves local api_key outside repo

- [ ] **Step 1: Write the failing test**
```python
# extend tests/test_llm_routing.py or tests/test_config_embed.py
def test_embed_config_defaults_to_hash(): ...
def test_embed_config_parses_api_and_ollama(): ...
```

- [ ] **Step 2: Run test to verify it fails**
Run: `pytest tests/test_config_embed.py` or routing test
Expected: FAIL

- [ ] **Step 3: Implement minimal config wiring**
In `src/onto3gpp/config.py`, parse `data["embed"]` into `EmbedConfig` dataclass; default hash/384/0.25/5; expose on `DomainConfig`. Keep `api_key` read but not committed (env override path). Add example stanza to `_template/config.yaml` and to `3gpp/config.yaml` as comments (provider=ollama example, api example commented out).

- [ ] **Step 4: Run tests**
Run: `pytest tests/test_config* -v` and `pytest tests/test_llm_routing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
`feat(config): embed block for swappable embedding (hash default, ollama/api via domain pack)`

---

### Task 4: Docs — ADR + architecture + roadmap/status

**Files:**
- Create: `docs/adr/0014-ai-merge-embedding-judge.md`
- Modify: `docs/architecture.md` — § AI-as-Judge / offline vs runtime, add embedding+judge flow
- Modify: `docs/roadmap.md` — Stage 9 / new Stage for ai-merge promotion status
- Modify: `docs/status.md` — gate metrics table + current stage

**Interfaces:**
- Consumes: prototype report.md + results.json (recall, P/R/F1)

- [ ] **Step 1: Draft ADR-0014** (CR: embedding+judge, alternatives: Dice unsafe, hash+LLM wins, swappable)
- [ ] **Step 2: Patch architecture.md** (§3 AI-as-judge, add ingestion embedding→judge diagram, CPU-only note)
- [ ] **Step 3: Update roadmap.md + status.md** (stage gate metrics, current stage)
- [ ] **Step 4: Verify docs render** (`rtk git diff` review)
- [ ] **Step 5: Commit**
`docs: ADR-0014 embedding+AI merge judge, architecture/roadmap/status updates`

---

### Task 5: Verification — eval harness + CI

**Files:** none new (uses `prototypes/ai-merge/evaluate.py` + optional new `scripts/eval_merge.py` thin wrapper);

- [ ] **Step 1: Run prototype harness offline**
Run: `.venv/bin/python prototypes/ai-merge/evaluate.py --embed hash --json` and `--embed ollama --llm` when live
Expected: hash P 1.0 / R 0.625+ / F1 0.77; ollama+LLM up to 1.0 when LLM live; no false merges

- [ ] **Step 2: Run full pytest**
Run: `pytest -q` (or `rtk pytest` if using wrapper)
Expected: all green + embed/merge_judge suites green

- [ ] **Step 3: Evidence → fix or promote**
If harness fails in main, tune threshold (0.25 is gate) or normalize (hyphen strip) — but never regress deterministically safe ADD on DCI pairs.

---
