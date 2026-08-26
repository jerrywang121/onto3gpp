# Progressive AI-Assisted Ingestion — Experiment Findings

**Date:** 2026-08-25
**Spec:** 3GPP TS 38.300 (i30), 532 parsed sections
**Prototype:** `prototypes/ai_ingest/ai_progressive.py`
**Models (local Ollama @ `http://localhost:11434`):**
- `deepseek-v4-flash:0731-cloud` — cheap, reliable on **extract** prompt only
- `minimax-m3:cloud` — reliable on **all three** prompt types (extract/verify/relations)

This document records the experiments, measurements, and decisions behind the
progressive AI-assisted ingestion prototype. It complements
[`ai_ingestion_report.md`](ai_ingestion_report.md) (which covers the earlier
"AI re-extract everything" experiment).

---

## 1. Design: three separate LLM calls per chunk

The prototype runs **three independent LLM calls** per section, each best-effort
with a deterministic fallback:

| Call | Task | Prompt | Fallback |
|---|---|---|---|
| (c1) `extract` | Identify NEW concepts | `EXTRACT_PROMPT_TEMPLATE` | `result={}` → keep deterministic candidates |
| (c2) `verify` | Judge deterministic candidates (Q2) | `VERIFY_PROMPT_TEMPLATE` | keep all candidates |
| (c3) `relations` | Propose relations to add/update (Q3) | `RELATIONS_PROMPT_TEMPLATE` | re-extract relations deterministically |

**Why three calls:** the local models return EMPTY when asked to produce several
distinct JSON fields in one prompt, or when given an exclusion list. Splitting
into single-task prompts with deterministic fallbacks is the robust design.

**Fallback monitoring:** each call records `_fallback = {extract, verify,
relations: bool}` (True when the model failed and the app fell back to
deterministic). The main loop tracks `fb_extract`/`fb_verify`/`fb_relations`
counters in the batch checkpoint. This exposes **silent model failures** that a
bare `try/except → result={}` would otherwise mask (a run can show `fail=0` even
if the model returns empty every time).

---

## 1b. Implementation changes (2026-08-25)

### Retry tracking

The LLM helpers (`ai_helpers.complete_json` / `complete_json_array`) retried
silently in a loop, so the number of re-tries per call was invisible. Added:

- `complete_json` / `complete_json_array` accept an optional `retries` list;
  the attempt count (1 = first try, >1 = retries) is appended on success.
- `process_chunk` records `_retries = {extract, verify, relations}` per section.
- The main loop accumulates `rt_extract` / `rt_verify` / `rt_relations` and
  prints them in each batch checkpoint.

This lets us monitor model reliability (how often a call needs >1 attempt) in
addition to the existing `fb_*` fallback counters.

### Explicit resume (`--resume`)

Resume was previously **implicit**: whenever the checkpoint files existed, the
run resumed from them. This made it easy to accidentally resume instead of
starting fresh. Now resume is **opt-in**:

- `--resume` loads the checkpoint dict/ontology and skips clauses already in
  `.progress.jsonl`. It errors clearly if the checkpoint files are missing.
- Without `--resume`, a fresh bootstrap is done (base dict, or `--empty`).

### Empty-bootstrap support (`--empty`)

To verify performance from **zero knowledge** (no base dict/ontology), added
`--empty` to bootstrap from an empty dict/ontology. This surfaced two
pyahocorasick bugs that only trigger on empty input:

- `compile/dictionary.build_automaton({})` called `make_automaton()` on an empty
  trie, which pyahocorasick rejects. **Fix:** return an empty `Dictionary` with
  `automaton=None` (its `find()` already guards on `None` → `[]`).
- `extract/relations._build_automaton` had the same empty-trie problem, and
  `extract_relations` called `automaton.iter()` on it. **Fix:** skip
  `make_automaton()` when empty, and return `[]` early when there are no known
  concepts.

### CLI usage

```bash
# Fresh empty run (zero knowledge)
... ai_progressive.py --parsed ... --dict /tmp/prog_dict.json \
    --ontology /tmp/prog_onto.json --config docs/domain/3gpp/config.yaml \
    --max-chars 1500 --empty

# Resume from last checkpoint
... ai_progressive.py --parsed ... --dict /tmp/prog_dict.json \
    --ontology /tmp/prog_onto.json --config docs/domain/3gpp/config.yaml \
    --resume
```

---

## 2. Model reliability findings

### 2.1 Prompt-type compatibility

| Model | extract | verify | relations |
|---|---|---|---|
| `deepseek-v4-flash:0731-cloud` | ✅ | ❌ empty | ❌ empty |
| `deepseek-v4-pro:0813-cloud` | ✅ | ❌ empty | ❌ empty |
| `minimax-m3:cloud` | ✅ | ✅ | ✅ |

`minimax-m3:cloud` is the only local model that reliably handles all three prompt
types. It returns ```json code fences (handled by `ai_helpers._extract_json`).

### 2.2 `max_tokens` impact on failure rate

**Hypothesis (user):** deepseek uses more thinking tokens per question, so a
small `max_tokens` truncates its output mid-thinking → empty/malformed JSON →
silent fallback.

**Test:** `test_max_tokens.py`, 7 fixed sections, `max_chars=1500`, extract
prompt, `attempts=3`.

| max_tokens | deepseek-v4-flash fail_rate | deepseek avg concepts | minimax-m3 fail_rate | minimax avg concepts |
|---|---|---|---|---|
| 1024 | **57%** (4/7) | 3.3 | **14%** (1/7) | 7.2 |
| 2048 | **14%** (1/7) | 6.8 | **0%** (0/7) | 9.6 |
| 4096 | **0%** (0/7) | 9.6 | **0%** (0/7) | 9.9 |

**Findings:**
- The hypothesis is **confirmed**: deepseek fails 57% at `max_tokens=1024` because
  it exhausts its output budget mid-thinking. It needs **≥4096**.
- minimax is robust: 14% at 1024, **0% from 2048** up.
- Failure rate correlates with concept quality: deepseek avg concepts rises
  3.3 → 9.6 as max_tokens grows.
- Wall-clock time is roughly flat across max_tokens (deepseek 11.8–18.6s,
  minimax 12.3–13.3s) — the model uses the tokens anyway; a small cap just
  truncates it.

**Decision:** `max_tokens=4096` for all models in `config.yaml`. If a model is
swapped in, re-run `test_max_tokens.py` to pick a safe cap.

---

## 3. Chunk-size A/B (throughput + quality)

**Why chars/s, not sections/s:** sections vary in size, so `sec/section`
conflates throughput with content volume. The real cost driver is the LLM calls,
bounded by `max_chars` per chunk. The fair metric is **chars/s** (content
throughput).

**Setup:** same model (`minimax-m3:cloud`), same `--limit 20` slice, only
`--max-chars` differs.

| Metric | max_chars=800 | max_chars=1500 |
|---|---|---|
| Wall time | 1089s | **631s** |
| Terms added | 142 | **206** |
| Relations added | 40 | **92** |
| fail | 0 | 0 |
| chars/s | 8/s | **19/s** |
| fallback (fb_*) | — | 0/0/0 |

**Findings:**
- **1500 is faster AND produces more.** Larger chunks mean fewer LLM round-trips
  per unit of content, and the model sees more context per call → more concepts
  and relations.
- 1500 had **zero fallbacks**, confirming the model stays reliable at 1500 chars.
- (The 800 run overlapped with a concurrent full run early on, slightly
  inflating its time; the 1500 run was clean. The advantage is still clear.)

**Direct 1500 verification** (`verify_1500.py`): the model returns 17–25 concepts
on 1500-char sections — it does **not** degrade at the larger chunk size.

---

## 4. Config-driven per-task model routing

The prototype now reads per-task model routing from the domain pack's
`config.yaml` instead of hard-coding one model:

```yaml
llm:
  models:
    extract:    { model: deepseek-v4-flash:0731-cloud, max_tokens: 4096 }  # cheap
    verify:     { model: minimax-m3:cloud,             max_tokens: 4096 }  # reliable
    relations:  { model: minimax-m3:cloud,             max_tokens: 4096 }  # reliable
```

- `ai_helpers.complete_json` accepts an optional `LLMConfig` that overrides
  model/provider/api_base/temperature/max_tokens.
- `ai_progressive.py` loads the domain config, builds a per-task `LLMConfig` map,
  and routes each of the three calls to its task model.
- **CLI overrides** (win over config):
  - `--config <path>` — which config.yaml to read
  - `--model <name>` — override the fallback model for all tasks
  - `--extract-model` / `--verify-model` / `--relations-model` — per-task override
  - `--max-tokens <n>` — override max_tokens for all tasks

**Smoke test** (5 sections, `--max-chars 1500`):
```
Task routing: extract=deepseek-v4-flash:0731-cloud(mt=4096), verify=minimax-m3:cloud(mt=4096), relations=minimax-m3:cloud(mt=4096)
[5/5] ok=5 fail=0 terms=48 rels=5 ... fb_extract=0 fb_verify=0 fb_relations=0
```
Routing works: extract uses the cheap deepseek, verify/relations use minimax,
all with `max_tokens=4096`, zero fallbacks.

---

## 5. Recommended parameter values

| Parameter | Value | Rationale |
|---|---|---|
| `max_tokens` | **4096** | deepseek needs ≥4096 to avoid thinking-token truncation (57% fail at 1024) |
| `max_chars` | **1500** | faster (19 vs 8 chars/s) and more productive (206 vs 142 terms) than 800 |
| extract model | `deepseek-v4-flash:0731-cloud` | cheap, reliable on extract prompt |
| verify/relations model | `minimax-m3:cloud` | only model reliable on all three prompt types |
| `VERIFY_CANDIDATE_CAP` | 10 | models fail on very long candidate lists |

---

## 6. Open questions / next steps

- Run the **full 532-section** progressive ingestion with the config-driven
  routing (extract=deepseek, verify/relations=minimax, `max_chars=1500`,
  `max_tokens=4096`) and evaluate against the baseline
  (MRR 0.6369, NDCG@10 0.6699, Recall@5 1.5833, Recall@10 2.3333).
- Compare the progressive dict/ontology vs the deterministic baseline to see
  whether gap-filling (not re-extraction) improves retrieval.
