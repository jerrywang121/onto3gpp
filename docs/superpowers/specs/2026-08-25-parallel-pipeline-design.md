# Parallel Pipelined AI Ingestion — Design

**Date:** 2026-08-25
**Status:** Approved
**Prototype:** `prototypes/ai_ingest/ai_progressive.py`
**Related:** `docs/ai_ingestion_progressive_findings.md` (§1 three-call design, §1b implementation changes)

---

## 1. Problem

The current `process_chunk` runs **three LLM calls sequentially** per section:

```
extract → verify → relations
```

Each call uses a **different model** (extract=`deepseek-v4-flash:0731-cloud`,
verify/relations=`minimax-m3:cloud`). Because the calls are sequential, the
models sit idle while the others run. With 3 distinct models, we are leaving
~2/3 of the model parallelism on the table.

**Goal:** run the three pipeline stages **concurrently across chunks** so that
at steady state 3 chunks are in flight simultaneously, each at a different
stage, each hitting a different model → up to 3× model parallelism.

```
time ──────────────────────────────────────────────►
chunk 1:  [extract]──[verify]──[relations]──apply
chunk 2:        [extract]──[verify]──[relations]──apply
chunk 3:              [extract]──[verify]──[relations]──apply
```

---

## 2. Key insight: stages are independent given a state snapshot

Each stage reads the **same** dict/ontology snapshot captured at chunk start:

- **extract** — reads `known` terms (from dict) + chunk text.
- **verify** — reads the deterministic `candidates` (from `extract_candidates`)
  + chunk text. Does **not** depend on extract's output.
- **relations** — reads `known_rels` + `candidate_rels` (from the current
  ontology) + chunk text. Does **not** depend on extract or verify output.

So the three stages have **no data dependency on each other** — they only share
the chunk's input snapshot. This makes a clean 3-stage pipeline possible: each
stage can run on a different chunk concurrently.

The **only** ordering constraint is at the **apply** step: results must be
applied in chunk order so the shared dict/ontology stays consistent (progressive
bootstrapping semantics).

---

## 3. Design

### 3.1 `ModelQueue` — one worker thread per `provider+model`

A small queue abstraction that owns a worker thread per unique model endpoint.

```python
class ModelQueue:
    def __init__(self, key: str, config: LLMConfig, maxsize: int = 4): ...
    def submit(self, prompt: str, *, max_tokens: int, temperature: float,
               attempts: int, retries: list) -> Future: ...
    def shutdown(self): ...
```

- `key` = `f"{config.provider}:{config.model}"` — one queue per unique model.
- Worker thread pulls jobs off a bounded `queue.Queue(maxsize)` and calls
  `complete_json(prompt, config.model, max_tokens=..., temperature=...,
  attempts=..., config=config, retries=retries)`.
- Returns a `concurrent.futures.Future`. The caller awaits it.
- Bounded queue (`maxsize=4`) prevents flooding ollama with unbounded in-flight
  requests.
- `retries` list is passed through so retry tracking (`rt_*`) still works.

### 3.2 Stage functions — split `process_chunk` into 3

Refactor `process_chunk` into three stage functions, each returning the raw
result dict for that stage. The shared snapshot (candidates, known, known_rels,
candidate_rels) is computed once per chunk and passed to all three.

```python
def stage_extract(section, snapshot, config) -> dict: ...
def stage_verify(section, snapshot, config) -> dict: ...
def stage_relations(section, snapshot, config) -> dict: ...
```

Each stage:
- builds its prompt,
- calls `complete_json` (via the queue),
- returns `(result, fallback_bool, retries_list)`.

### 3.3 Pipeline driver — ordered apply

```python
def run_pipeline(sections, dictionary, onto, queues, max_chars, ...):
    pending = {}   # clause -> (section, snapshot, futures)
    for i, section in enumerate(sections):
        if section.clause in done:
            continue
        snapshot = compute_snapshot(section, dictionary, onto, max_chars)
        f_extract = queues["extract"].submit(...)
        f_verify  = queues["verify"].submit(...)
        f_relations = queues["relations"].submit(...)
        pending[section.clause] = (section, snapshot, f_extract, f_verify, f_relations)
        # apply in order: drain any completed chunks whose clause is the
        # earliest not-yet-applied
        while pending and pending[next_clause].all_done():
            apply_one(...)
```

- **Ordered apply:** a chunk's result is applied only when (a) all 3 of its
  futures are done **and** (b) it is the earliest not-yet-applied clause. This
  preserves progressive-bootstrap semantics exactly.
- **Checkpoint write** moves to the apply step (see §4).

### 3.4 CLI

- `--parallel` flag: enables the pipeline. Default remains sequential.
- `--workers` (optional, default 1): number of chunks in flight per stage
  (bounded by queue `maxsize`). For v1, keep it simple: `--parallel` uses
  `maxsize=4` per queue; no separate workers knob.

---

## 4. Resume / checkpoint compatibility (unchanged semantics)

The current resume logic is preserved **byte-for-byte**:

- `done` set built from `.progress.jsonl` lines (`clause` field).
- Loop skips `section.clause in done`.
- Log schema unchanged: `{"clause", "terms_added", "relations_added", "match",
  "result"}`.

**Changes required:**

1. **Checkpoint write moves** from the submission loop to the **apply step**.
   Today it's written right after `apply_result` inside the loop; in the
   parallel design it's written when a chunk's relations future completes and
   it's the next-in-order clause. This is a structural move, not a semantic
   change.
2. **In-flight chunks on crash:** if the process dies mid-pipeline, chunks with
   extract/verify done but relations not yet applied are simply **not in
   `done`**, so on resume they're reprocessed from scratch. No corruption — just
   a little rework. Identical to today's behavior.

**Result:** existing checkpoints (including the running 110/532 run) remain
resumable by the parallel code, because the log schema and `done` semantics are
unchanged.

---

## 5. Error handling

- Each stage call is wrapped in `try/except` → returns `{}` + `fallback=True`,
  exactly as today. A flaky stage never blocks the pipeline; it just falls back
  to deterministic.
- `_fallback` / `_retries` / `_match` / `_candidates` tracking is preserved
  across the stage split so the counters and log stay accurate.
- If a future raises (unexpected), the chunk is marked failed and logged with
  `{"clause", "error", "result": {}}` — same as today's except branch.

---

## 6. Testing

- **Unit tests** for `ModelQueue`: submit returns a Future; worker calls
  `complete_json` with the right config; bounded queue; shutdown drains.
- **Unit tests** for the stage functions: each returns the expected result dict
  given a fake `complete_json`.
- **Unit tests** for the pipeline driver: with a fake queue (deterministic
  futures), verify ordered apply, checkpoint write on apply, resume skip, and
  crash-recovery (unapplied chunks reprocessed).
- **Smoke test** (5 sections) against real ollama: parallel run produces the
  same dict/ontology as the sequential run for the same input, and `--resume`
  continues correctly.

---

## 7. Out of scope (YAGNI)

- No dynamic worker scaling.
- No cross-model load balancing beyond the per-model queue.
- No change to the sequential path (it stays as the default / fallback).
- No change to the log schema or checkpoint format.
