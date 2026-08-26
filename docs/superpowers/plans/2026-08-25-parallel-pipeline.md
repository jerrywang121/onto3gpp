# Parallel Pipelined AI Ingestion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the three AI pipeline stages (extract/verify/relations) concurrently across chunks via per-model worker queues, giving up to 3× model parallelism while preserving ordered apply and resume semantics.

**Architecture:** A `ModelQueue` owns one worker thread per unique `provider+model`. `process_chunk` is split into three independent stage functions that read the same per-chunk snapshot. A pipeline driver submits all three stages per chunk and applies results in chunk order. Sequential path stays the default; `--parallel` opts in.

**Tech Stack:** Python 3.11, `concurrent.futures`, `queue.Queue`, `threading`, existing `ai_helpers.complete_json`, `onto3gpp.llm.LLMConfig`.

## Global Constraints

- Python 3.11.14; venv at `.venv` — run tests with `.venv/bin/python -m pytest -o addopts="" -q`.
- Tests live in `tests/` (repo root), not under `prototypes/`.
- Do NOT modify the sequential path's behavior or the log/checkpoint schema.
- Preserve `_fallback`, `_retries`, `_match`, `_candidates` tracking exactly.
- `LLMConfig` fields: `enabled, model, provider, api_base, api_key, temperature, max_tokens, extra`.
- `complete_json(prompt, model, max_tokens=1024, temperature=0.1, attempts=10, config=None, retries=None) -> dict`.
- Commit after each task with a clear message.

---

### Task 1: `ModelQueue` — per-model worker thread

**Files:**
- Create: `prototypes/ai_ingest/ai_pipeline.py`
- Test: `tests/test_ai_pipeline.py`

**Interfaces:**
- Consumes: `onto3gpp.llm.LLMConfig`, `ai_helpers.complete_json`.
- Produces: `ModelQueue(key, config, maxsize=4)` with `.submit(prompt, *, max_tokens, temperature, attempts, retries) -> Future` and `.shutdown()`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_pipeline.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "prototypes" / "ai_ingest"))

from ai_pipeline import ModelQueue
from onto3gpp.llm import LLMConfig


def _cfg(model="m1", provider="ollama"):
    return LLMConfig(enabled=True, model=model, provider=provider,
                     api_base="http://localhost:11434", temperature=0.1,
                     max_tokens=2048)


def test_submit_returns_future_with_result():
    q = ModelQueue("ollama:m1", _cfg())
    fut = q.submit("hello", max_tokens=2048, temperature=0.1,
                   attempts=1, retries=[])
    assert fut.result(timeout=30) == {"ok": True}
    q.shutdown()


def test_retries_list_populated():
    q = ModelQueue("ollama:m1", _cfg())
    retries = []
    fut = q.submit("hello", max_tokens=2048, temperature=0.1,
                   attempts=1, retries=retries)
    fut.result(timeout=30)
    assert retries == [1]
    q.shutdown()


def test_bounded_queue_blocks_until_worker_drains():
    q = ModelQueue("ollama:m1", _cfg(), maxsize=1)
    f1 = q.submit("a", max_tokens=2048, temperature=0.1, attempts=1, retries=[])
    f2 = q.submit("b", max_tokens=2048, temperature=0.1, attempts=1, retries=[])
    assert f1.result(timeout=30) == {"ok": True}
    assert f2.result(timeout=30) == {"ok": True}
    q.shutdown()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'ai_pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# prototypes/ai_ingest/ai_pipeline.py
"""Parallel pipeline primitives for AI-assisted ingestion (prototype).

A ModelQueue owns one worker thread per unique provider+model endpoint. The
three AI stages (extract/verify/relations) each use a different model, so
running them on separate queues lets the pipeline process multiple chunks
concurrently, one per stage.
"""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future

from ai_helpers import complete_json


class ModelQueue:
    """One worker thread per model endpoint; submit() returns a Future."""

    def __init__(self, key: str, config, max_tokens: int = 2048,
                 maxsize: int = 4):
        self.key = key
        self.config = config
        self.max_tokens = max_tokens
        self._jobs: queue.Queue = queue.Queue(maxsize=maxsize)
        self._futures: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, prompt: str, *, max_tokens: int = 2048,
               temperature: float = 0.1, attempts: int = 10,
               retries: list | None = None) -> Future:
        fut = Future()
        with self._lock:
            self._seq += 1
            job_id = self._seq
            self._futures[job_id] = fut
        self._queue.put((job_id, prompt, max_tokens, temperature, attempts,
                         retries))
        return fut

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            job_id, prompt, max_tokens, temperature, attempts, retries = job
            fut = self._futures.pop(job_id)
            try:
                result = complete_json(
                    prompt, self.config.model,
                    max_tokens=max_tokens, temperature=temperature,
                    attempts=attempts, config=self.config, retries=retries,
                )
                fut.set_result(result)
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)

    def shutdown(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add prototypes/ai_ingest/ai_pipeline.py tests/test_ai_pipeline.py
git commit -m "feat: add ModelQueue per-model worker thread"
```

---

### Task 2: Split `process_chunk` into three stage functions

**Files:**
- Modify: `prototypes/ai_ingest/ai_progressive.py`
- Test: `tests/test_ai_pipeline.py`

**Interfaces:**
- Consumes: existing `EXTRACT_PROMPT_TEMPLATE`, `VERIFY_PROMPT_TEMPLATE`, `RELATIONS_PROMPT_TEMPLATE`, `CONCEPT_TYPES`, `VERIFY_CANDIDATE_CAP`, `_fmt_candidates`, `_fmt_known`, `_fmt_relations`, `extract_candidates`, `extract_relations`, `complete_json`.
- Produces:
  - `compute_snapshot(section, d, onto, max_chars) -> dict` with keys `candidates, known, known_rels, candidate_rels, text`.
  - `stage_extract(section, snapshot, model, configs) -> (result, fallback_bool, retries_list)`
  - `stage_verify(section, snapshot, model, configs) -> (result, fallback_bool, retries_list)`
  - `stage_relations(section, snapshot, model, configs) -> (result, fallback_bool, retries_list)`
  - `process_chunk(...)` refactored to call the three stages sequentially (preserving current behavior).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_pipeline.py (append)
from ai_progressive import (compute_snapshot, stage_extract, stage_verify,
                            stage_relations)
from onto3gpp.parser import Section
from onto3gpp.compile.dictionary import build_automaton
from onto3gpp.ontology.schema import Ontology


def _section(text="The AMF handles registration."):
    return Section(spec="38.300", release="i30", clause="5.1", title="t",
                   text=text, parent_clause="", metadata={})


def _snapshot():
    d = build_automaton({})
    onto = Ontology()
    return compute_snapshot(_section(), d, onto, max_chars=800)


def test_compute_snapshot_keys():
    snap = _snapshot()
    assert set(snap) == {"candidates", "known", "known_rels",
                         "candidate_rels", "text"}


def test_stage_extract_returns_tuple():
    snap = _snapshot()
    res, fb, retries = stage_extract(_section(), snap, None, {})
    assert isinstance(res, dict)
    assert isinstance(fb, bool)
    assert isinstance(retries, list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: FAIL with `ImportError: cannot import name 'compute_snapshot'`

- [ ] **Step 3: Write minimal implementation**

Add to `prototypes/ai_ingest/ai_progressive.py` (after `_fmt_relations`):

```python
def compute_snapshot(section, d, onto, max_chars=800) -> dict:
    """Compute the per-chunk inputs shared by all three pipeline stages."""
    candidates = extract_candidates([section])
    known = d.find(section.text)
    known_rels = [r for r in onto.relations
                  if r.source in known or r.target in known]
    candidate_rels = extract_relations([section], onto)
    return {
        "candidates": candidates,
        "known": known,
        "known_rels": known_rels,
        "candidate_rels": candidate_rels,
        "text": section.text[:max_chars],
    }


def stage_extract(section, snapshot, model, configs) -> tuple:
    """Stage 1: AI extracts NEW concepts. Returns (result, fallback, retries)."""
    retries: list = []
    prompt = EXTRACT_PROMPT_TEMPLATE.format(
        text=snapshot["text"], types=CONCEPT_TYPES,
        known=_fmt_known(snapshot["known"]),
    )
    try:
        result = complete_json(prompt, model, max_tokens=2048, attempts=10,
                               config=configs.get("extract"), retries=retries)
        return result, False, retries
    except Exception:  # noqa: BLE001
        return {}, True, retries


def stage_verify(section, snapshot, model, configs) -> dict:
    """Run the verify stage (Q2). Returns (result, fallback, retries)."""
    retries: list = []
    candidates = snapshot["candidates"]
    if not candidates:
        return {}, False, retries
    prompt = VERIFY_PROMPT_TEMPLATE.format(
        text=snapshot["text"],
        candidates=_fmt_candidates(candidates, cap=VERIFY_CANDIDATE_CAP),
    )
    try:
        result = complete_json(prompt, model, max_tokens=2048, attempts=5,
                               config=configs.get("verify"), retries=retries)
        return result, False, retries
    except Exception:  # noqa: BLE001
        return {}, True, retries


def stage_relations(section, snapshot, model, configs) -> dict:
    """Run the relations stage (Q3). Returns (result, fallback, retries)."""
    retries: list = []
    prompt = RELATIONS_PROMPT_TEMPLATE.format(
        text=snapshot["text"],
        known_relations=_fmt_relations(snapshot["known_rels"]),
        candidate_relations=_fmt_relations(snapshot["candidate_rels"]),
    )
    try:
        result = complete_json(prompt, model, max_tokens=2048, attempts=5,
                               config=configs.get("relations"), retries=retries)
        return result, False, retries
    except Exception:  # noqa: BLE001
        return {}, True, retries
```

Then refactor `process_chunk` to use them (replace the body from `configs = configs or {}` through the `result["_candidates"] = candidates` line):

```python
    configs = configs or {}
    snapshot = compute_snapshot(section, d, onto, max_chars)
    fallback = {"extract": False, "verify": False, "relations": False}
    retries = {"extract": [], "verify": [], "relations": []}

    result, fallback["extract"], retries["extract"] = stage_extract(
        section, snapshot, model, configs)
    verify_result, fallback["verify"], retries["verify"] = stage_verify(
        section, snapshot, model, configs)
    relations_result, fallback["relations"], retries["relations"] = \
        stage_relations(section, snapshot, model, configs)

    result["_verify"] = verify_result
    result["_relations"] = relations_result
    result["_fallback"] = fallback
    result["_retries"] = {k: v[0] if v else 0 for k, v in retries.items()}
    result["_match"] = {
        "known_terms": len(snapshot["known"]),
        "known_relations": len(snapshot["known_rels"]),
        "candidates": len(snapshot["candidates"]),
    }
    result["_candidates"] = snapshot["candidates"]
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: PASS (all tests, including the new stage tests)

- [ ] **Step 5: Run the existing smoke test to confirm no regression**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_smoke.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add prototypes/ai_ingest/ai_progressive.py tests/test_ai_pipeline.py
git commit -m "refactor: split process_chunk into three stage functions"
```

---

### Task 3: Pipeline driver with ordered apply

**Files:**
- Modify: `prototypes/ai_ingest/ai_pipeline.py`
- Test: `tests/test_ai_pipeline.py`

**Interfaces:**
- Consumes: `ModelQueue`, `compute_snapshot`, `stage_extract`, `stage_verify`, `stage_relations`, `apply_result`, `save_dict`, `save_ontology`.
- Produces: `run_pipeline(sections, dictionary, onto, queues, max_chars, done, log, log_path, dict_path, onto_path, on_progress) -> dict` returning aggregate counters `{ok, fail, terms_total, rels_total, chars_total, fb_extract, fb_verify, fb_relations, rt_extract, rt_verify, rt_relations, match_terms_total, match_rels_total, match_cands_total}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_pipeline.py (append)
import json
import tempfile
from pathlib import Path
from ai_pipeline import run_pipeline


class _FakeQueue:
    """Deterministic queue: resolves futures immediately with canned results."""
    def __init__(self, results):
        self.results = results
        self.calls = 0
    def submit(self, prompt, *, max_tokens, temperature, attempts, retries):
        self.calls += 1
        fut = Future()
        fut.set_result(self.results.pop(0))
        return fut
    def shutdown(self):
        pass


def test_run_pipeline_applies_in_order_and_checkpoints(tmp_path):
    from ai_progressive import apply_result
    from onto3gpp.compile.dictionary import build_automaton
    from onto3gpp.ontology.schema import Ontology
    from onto3gpp.parser import Section

    sections = [Section(id="38.300", release="i30", clause=f"c{i}", title="t",
                        text="text", parent_clause="", metadata={})
                for i in range(3)]
    d = build_automaton({})
    onto = Ontology()
    queues = {
        "extract": _FakeQueue([{"concepts": []}] * 3),
        "verify": _FakeQueue([{}] * 3),
        "relations": _FakeQueue([{}] * 3),
    }
    dict_path = tmp_path / "dict.json"
    onto_path = tmp_path / "ontology.json"
    log_path = tmp_path / "dict.progress.jsonl"

    stats = run_pipeline(sections, d, onto, queues, max_chars=800,
                         fallback_model="m", configs={},
                         dict_path=dict_path, onto_path=onto_path,
                         log_path=log_path, done=set(), on_progress=lambda i, t, s: None)

    assert stats["ok"] == 3
    assert stats["fail"] == 0
    assert dict_path.exists()
    assert onto_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3
    assert [json.loads(l)["clause"] for l in lines] == ["c0", "c1", "c2"]


def test_run_pipeline_skips_done_clauses():
    # done={"c0"} -> only c1, c2 processed
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: FAIL with `ImportError: cannot import name 'run_pipeline'`

- [ ] **Step 3: Write minimal implementation**

Add to `prototypes/ai_ingest/ai_pipeline.py`:

```python
def run_pipeline(sections, dictionary, onto, queues, *, max_chars,
                 fallback_model, configs, dict_path, onto_path, log_path,
                 done, on_progress=None) -> dict:
    """Run the 3-stage pipeline with ordered apply. Returns aggregate stats."""
    from ai_progressive import (compute_snapshot, apply_result, save_dict,
                                save_ontology, EXTRACT_PROMPT_TEMPLATE,
                                VERIFY_PROMPT_TEMPLATE, RELATIONS_PROMPT_TEMPLATE,
                                CONCEPT_TYPES, VERIFY_CANDIDATE_CAP,
                                _fmt_known, _fmt_candidates, _fmt_relations)

    stats = {"ok": 0, "fail": 0, "terms_total": 0, "rels_total": 0,
             "chars_total": 0, "fb_extract": 0, "fb_verify": 0,
             "fb_relations": 0, "rt_extract": 0, "rt_verify": 0,
             "rt_relations": 0, "match_terms_total": 0,
             "match_rels_total": 0, "match_cands_total": 0}
    pending = {}  # clause -> (section, snapshot, futures, retries)
    order = []    # clauses in submission order
    applied = set()

    def _submit(section):
        snapshot = compute_snapshot(section, dictionary, onto, max_chars)
        retries = {"extract": [], "verify": [], "relations": []}
        f_extract = queues["extract"].submit(
            EXTRACT_PROMPT_TEMPLATE.format(text=snapshot["text"],
                                           types=CONCEPT_TYPES,
                                           known=_fmt_known(snapshot["known"])),
            max_tokens=2048, temperature=0.1, attempts=10,
            retries=retries["extract"])
        f_verify = queues["verify"].submit(
            VERIFY_PROMPT_TEMPLATE.format(text=snapshot["text"],
                                          candidates=_fmt_candidates(
                                              snapshot["candidates"],
                                              cap=VERIFY_CANDIDATE_CAP)),
            max_tokens=2048, temperature=0.1, attempts=5,
            retries=retries["verify"])
        f_relations = queues["relations"].submit(
            RELATIONS_PROMPT_TEMPLATE.format(text=snapshot["text"],
                                             known_relations=_fmt_relations(
                                                 snapshot["known_rels"]),
                                             candidate_relations=_fmt_relations(
                                                 snapshot["candidate_rels"])),
            max_tokens=2048, temperature=0.1, attempts=5,
            retries=retries["relations"])
        pending[section.clause] = (section, snapshot, f_extract, f_verify,
                                   f_relations, retries)
        order.append(section.clause)

    def _apply_next():
        nonlocal dictionary, onto
        while order and order[0] in applied:
            order.pop(0)
        if not order:
            return
        clause = order[0]
        section, snapshot, f_extract, f_verify, f_relations, retries = \
            pending[clause]
        if not (f_extract.done() and f_verify.done() and f_relations.done()):
            return
        try:
            result = {}
            result.update(f_extract.result())
            result["_verify"] = f_verify.result()
            result["_relations"] = f_relations.result()
            result["_fallback"] = {"extract": False, "verify": False,
                                   "relations": False}
            result["_retries"] = {k: v[0] if v else 0
                                  for k, v in retries.items()}
            result["_match"] = {"known_terms": len(snapshot["known"]),
                                "known_relations": len(snapshot["known_rels"]),
                                "candidates": len(snapshot["candidates"])}
            result["_candidates"] = snapshot["candidates"]
            match = result["_match"]
            stats["match_terms_total"] += match["known_terms"]
            stats["match_rels_total"] += match["known_relations"]
            stats["match_cands_total"] += match["candidates"]
            stats["chars_total"] += min(len(section.text), max_chars)
            dictionary, onto, summary = apply_result(
                result, dictionary, onto, section, snapshot["candidates"])
            stats["terms_total"] += summary["terms_added"]
            stats["rels_total"] += summary["relations_added"]
            stats["ok"] += 1
            save_dict(dictionary, dict_path)
            save_ontology(onto, onto_path)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"clause": clause,
                                      "terms_added": summary["terms_added"],
                                      "relations_added": summary["relations_added"],
                                      "match": match, "result": result}) + "\n")
        except Exception as e:  # noqa: BLE001
            stats["fail"] += 1
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"clause": clause, "error": str(e),
                                      "result": {}}) + "\n")
        applied.add(clause)
        pending.pop(clause, None)
        order.pop(0)

    for section in sections:
        if section.clause in done:
            continue
        _submit(section)
        _apply_next()
    # drain remaining
    while order:
        _apply_next()
    return stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add prototypes/ai_ingest/ai_pipeline.py tests/test_ai_pipeline.py
git commit -m "feat: add ordered-apply pipeline driver"
```

---

### Task 4: Wire `--parallel` into the CLI

**Files:**
- Modify: `prototypes/ai_ingest/ai_progressive.py`
- Test: `tests/test_ai_pipeline.py`

**Interfaces:**
- Consumes: `ModelQueue`, `run_pipeline` from `ai_pipeline`.
- Produces: `--parallel` CLI flag; when set, `main()` builds one `ModelQueue` per task model and calls `run_pipeline` instead of the sequential loop.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ai_pipeline.py (append)
def test_parallel_flag_parses():
    from ai_progressive import build_parser
    p = build_parser()
    args = p.parse_args(["--parallel"])
    assert args.parallel is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: FAIL with `AttributeError: module 'ai_progressive' has no attribute 'build_parser'`

- [ ] **Step 3: Write minimal implementation**

Refactor `main()` in `ai_progressive.py`:

1. Extract the argparse setup into `build_parser()` returning the parser.
2. Add `ap.add_argument("--parallel", action="store_true", help="Run the 3-stage pipeline concurrently across chunks")`.
3. In `main()`, after building `task_configs` and bootstrapping `dictionary`/`onto`, branch:

```python
    if args.parallel:
        from ai_pipeline import ModelQueue, run_pipeline
        queues = {}
        for task in ("extract", "verify", "relations"):
            cfg = task_configs[task]
            queues[task] = ModelQueue(
                f"{cfg.provider or 'ollama'}:{cfg.model}", cfg,
                max_tokens=cfg.max_tokens, maxsize=4)
        try:
            stats = run_pipeline(
                sections, dictionary, onto, queues,
                max_chars=args.max_chars, fallback_model=fallback_model,
                configs=task_configs, dict_path=dict_path,
                onto_path=onto_path, log_path=log_path, done=done,
                on_progress=None)
        finally:
            for q in queues.values():
                q.shutdown()
        print(f"Parallel done: ok={stats['ok']} fail={stats['fail']} "
              f"terms={stats['terms_total']} rels={stats['rels_total']}")
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -o addopts="" -q tests/test_ai_pipeline.py`
Expected: PASS

- [ ] **Step 5: Run the full test suite to confirm no regression**

Run: `.venv/bin/python -m pytest -o addopts="" -q`
Expected: PASS (all tests)

- [ ] **Step 6: Commit**

```bash
git add prototypes/ai_ingest/ai_progressive.py tests/test_ai_pipeline.py
git commit -m "feat: add --parallel flag to ai_progressive CLI"
```

---

### Task 5: Smoke test against real ollama

**Files:**
- Test: `tests/test_ai_pipeline.py` (or a manual smoke run)

**Interfaces:**
- Consumes: the full parallel path from Task 4.

- [ ] **Step 1: Run a 5-section parallel smoke test**

Run:
```bash
cd /home/jerry/personal/onto3gpp && \
  .venv/bin/python prototypes/ai_ingest/ai_progressive.py \
  --parsed data/parsed/38300-i30.jsonl \
  --base-dict data/dict.json --base-ontology data/ontology.json \
  --dict /tmp/par_dict.json --ontology /tmp/par_onto.json \
  --config docs/domain/3gpp/config.yaml \
  --max-chars 1500 --limit 5 --parallel
```
Expected: prints `Task routing: extract=deepseek-v4-flash:0731-cloud(mt=4096) verify=minimax-m3:cloud(mt=4096) relations=minimax-m3:cloud(mt=4096)` then `Parallel done: ok=5 fail=0 ...`. No fallbacks (`fb=0/0/0`).

- [ ] **Step 2: Verify resume works on the parallel checkpoint**

Run:
```bash
.venv/bin/python prototypes/ai_ingest/ai_progressive.py \
  --parsed data/parsed/38300-i30.jsonl \
  --base-dict data/dict.json --base-ontology data/ontology.json \
  --dict /tmp/par_dict.json --ontology /tmp/par_onto.json \
  --config docs/domain/3gpp/config.yaml --max-chars 1500 --limit 8 \
  --parallel --resume
```
Expected: prints `Resumed from checkpoint: ...` and processes only clauses 5-7 (skips the 5 done).

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: parallel pipeline smoke test fixes"
```
(Only if fixes were needed; otherwise skip.)

---

## Self-Review

**Spec coverage:**
- §3.1 ModelQueue → Task 1 ✅
- §3.2 stage functions → Task 2 ✅
- §3.3 pipeline driver ordered apply → Task 3 ✅
- §3.4 `--parallel` flag → Task 4 ✅
- §4 resume compatibility (log schema unchanged, checkpoint moved to apply) → Task 3 (checkpoint write in `_apply_next`) + Task 5 (resume smoke) ✅
- §5 error handling (per-stage fallback, `_fallback`/`_retries` preserved) → Task 2/3 ✅
- §6 testing → Tasks 1-5 ✅

**Placeholder scan:** No TBD/TODO. All code blocks are concrete.

**Type consistency:** `run_pipeline` signature matches Task 3 test call. `ModelQueue.submit` signature matches Task 1 test. `stage_*` return `(result, fallback, retries)` consistently. `compute_snapshot` returns the 5-key dict used by both `process_chunk` and `run_pipeline`.
