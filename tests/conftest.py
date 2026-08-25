# tests/conftest.py
"""Shared fixtures for repo-root tests.

The brief's test_ai_pipeline.py expects complete_json to return {"ok": True}
without a live model. Patch ai_pipeline.complete_json so the ModelQueue worker
uses a deterministic fake instead of making a real litellm call.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "prototypes" / "ai_ingest"))

import ai_pipeline  # noqa: E402


@pytest.fixture(autouse=True)
def _mock_complete_json(monkeypatch):
    def fake_complete_json(prompt, model, max_tokens=1024, temperature=0.1,
                           attempts=10, config=None, retries=None):
        if retries is not None:
            retries.append(1)
        return {"ok": True}

    monkeypatch.setattr(ai_pipeline, "complete_json", fake_complete_json)
