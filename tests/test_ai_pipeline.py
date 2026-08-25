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
