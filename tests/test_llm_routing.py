"""Tests for multi-model LLM routing (Stage 8)."""

from __future__ import annotations

import pytest

from onto3gpp.llm import LLMClient, LLMConfig, LLMDisabledError


def test_llm_config_models_map():
    cfg = LLMConfig.from_dict(
        {
            "enabled": True,
            "default": {"provider": "openai", "model": "gpt-4o-mini"},
            "models": {
                "judge": {"provider": "openai", "model": "gpt-4o"},
                "extract": {"provider": "ollama", "model": "llama3"},
            },
        }
    )
    assert cfg.default.model == "gpt-4o-mini"
    assert cfg.models["judge"].model == "gpt-4o"
    assert cfg.models["extract"].model == "llama3"


def test_llm_config_flat_block_is_default():
    # Backward-compatible flat form treated as default.
    cfg = LLMConfig.from_dict(
        {"enabled": True, "model": "gpt-4o-mini", "provider": "openai"}
    )
    assert cfg.default.model == "gpt-4o-mini"
    assert cfg.models == {}


def test_llm_config_models_empty_by_default():
    cfg = LLMConfig.from_dict(None)
    assert cfg.models == {}
    assert cfg.default.model == "gpt-4o-mini"


def test_for_task_resolves_named_model():
    cfg = LLMConfig.from_dict(
        {
            "enabled": True,
            "default": {"model": "gpt-4o-mini"},
            "models": {"judge": {"model": "gpt-4o"}},
        }
    )
    client = LLMClient(cfg)
    judge = client.for_task("judge")
    assert judge.config.model == "gpt-4o"
    # unknown task falls back to default
    assert client.for_task("bogus").config.model == "gpt-4o-mini"


def test_for_task_returns_bound_client():
    cfg = LLMConfig.from_dict(
        {"enabled": True, "models": {"extract": {"model": "llama3"}}}
    )
    client = LLMClient(cfg)
    extract = client.for_task("extract")
    assert extract.config.model == "llama3"
    assert extract.config.enabled is True


def test_for_task_disabled_raises():
    cfg = LLMConfig.from_dict({"enabled": False, "models": {"judge": {"model": "gpt-4o"}}})
    client = LLMClient(cfg)
    with pytest.raises(LLMDisabledError):
        client.for_task("judge").complete("hi")
