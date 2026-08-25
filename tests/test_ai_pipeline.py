# tests/test_ai_pipeline.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "prototypes" / "ai_ingest"))

import pytest

import ai_progressive
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


@pytest.fixture
def _mock_progressive_complete_json(monkeypatch):
    """Patch ai_progressive.complete_json (a different symbol from
    ai_pipeline.complete_json) so the stage functions return deterministically
    without a live model."""
    def fake_complete_json(prompt, model, max_tokens=1024, temperature=0.1,
                           attempts=10, config=None, retries=None):
        if retries is not None:
            retries.append(1)
        return {}

    monkeypatch.setattr(ai_progressive, "complete_json", fake_complete_json)


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


def test_stage_extract_returns_tuple(_mock_progressive_complete_json):
    snap = _snapshot()
    res, fb, retries = stage_extract(_section(), snap, None, {})
    assert isinstance(res, dict)
    assert isinstance(fb, bool)
    assert isinstance(retries, list)


# --- Task 3: run_pipeline (ordered apply) ---

import json
from concurrent.futures import Future

from ai_pipeline import run_pipeline


class _FakeQueue:
    """Deterministic queue: resolves futures immediately with canned results."""
    def __init__(self, results):
        self.results = results
        self.calls = 0
    def submit(self, prompt, *, max_tokens, temperature, attempts, retries):
        self.calls += 1
        if retries is not None:
            retries.append(1)
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

    sections = [Section(spec="38.300", release="i30", clause=f"c{i}", title="t",
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
    assert stats["rt_extract"] == 3
    assert stats["rt_verify"] == 3
    assert stats["rt_relations"] == 3
    assert dict_path.exists()
    assert onto_path.exists()
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 3
    assert [json.loads(l)["clause"] for l in lines] == ["c0", "c1", "c2"]


def test_run_pipeline_skips_done_clauses(tmp_path):
    from onto3gpp.compile.dictionary import build_automaton
    from onto3gpp.ontology.schema import Ontology
    from onto3gpp.parser import Section

    sections = [Section(spec="38.300", release="i30", clause=f"c{i}", title="t",
                        text="text", parent_clause="", metadata={})
                for i in range(3)]
    d = build_automaton({})
    onto = Ontology()
    queues = {
        "extract": _FakeQueue([{"concepts": []}] * 2),
        "verify": _FakeQueue([{}] * 2),
        "relations": _FakeQueue([{}] * 2),
    }
    dict_path = tmp_path / "dict.json"
    onto_path = tmp_path / "ontology.json"
    log_path = tmp_path / "dict.progress.jsonl"

    stats = run_pipeline(sections, d, onto, queues, max_chars=800,
                         fallback_model="m", configs={},
                         dict_path=dict_path, onto_path=onto_path,
                         log_path=log_path, done={"c0"},
                         on_progress=lambda i, t, s: None)

    assert stats["ok"] == 2
    assert stats["fail"] == 0
    lines = log_path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(l)["clause"] for l in lines] == ["c1", "c2"]


# --- Task 4: --parallel CLI flag ---

def test_parallel_flag_parses():
    from ai_progressive import build_parser
    p = build_parser()
    args = p.parse_args(
        ["--parsed", "x.jsonl", "--base-dict", "d.json", "--base-ontology", "o.json",
         "--dict", "out.json", "--ontology", "out_onto.json", "--parallel"]
    )
    assert args.parallel is True
