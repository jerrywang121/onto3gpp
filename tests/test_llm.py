"""Tests for the configurable LLM client abstraction (external AI hooks)."""

from __future__ import annotations

import pytest

from onto3gpp.llm import (
    LLMClient,
    LLMConfig,
    LLMDisabledError,
    _extract_json,
)


def test_llm_config_from_dict_filters_unknown_keys():
    cfg = LLMConfig.from_dict(
        {
            "enabled": True,
            "model": "local-model",
            "bogus": "ignored",
            "temperature": 0.5,
        }
    )
    assert cfg.enabled is True
    assert cfg.model == "local-model"
    assert cfg.temperature == 0.5
    assert not hasattr(cfg, "bogus")


def test_llm_config_from_dict_none_returns_defaults():
    cfg = LLMConfig.from_dict(None)
    assert cfg.enabled is False
    assert cfg.model == "gpt-4o-mini"


def test_extract_json_plain():
    assert _extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_code_fence():
    text = '```json\n{"a": 1}\n```'
    assert _extract_json(text) == {"a": 1}


def test_client_disabled_raises():
    client = LLMClient(LLMConfig(enabled=False))
    with pytest.raises(LLMDisabledError):
        client.complete("hello")


def test_client_complete_uses_call():
    class FakeClient(LLMClient):
        def _call(self, prompt: str) -> str:
            return f"echo:{prompt}"

    client = FakeClient(LLMConfig(enabled=True))
    assert client.complete("hi") == "echo:hi"


def test_client_complete_json_parses():
    class FakeClient(LLMClient):
        def _call(self, prompt: str) -> str:
            return '{"proposals": []}'

    client = FakeClient(LLMConfig(enabled=True))
    assert client.complete_json("x") == {"proposals": []}
