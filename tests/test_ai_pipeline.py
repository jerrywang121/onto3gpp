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
