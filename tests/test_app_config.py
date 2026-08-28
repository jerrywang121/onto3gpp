"""Tests for app-level AI config (config/app.yaml, ADR-0015)."""

from pathlib import Path

import pytest


def test_cmdc_resolves_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "user_test_123")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    p = tmp_path / "app.yaml"
    p.write_text(
        """
llm:
  enabled: true
  default:
    provider: cmdc
    model: minimax/minimax-m3-free
    api_base: https://api.commandcode.ai/provider/v1
    api_key_env: COMMAND_CODE_API_KEY
embed:
  kind: hash
  dim: 384
"""
    )
    from onto3gpp.app_config import load_app_config

    cfg = load_app_config(p)
    assert cfg.llm.enabled is True
    assert cfg.llm.provider == "cmdc"
    assert cfg.llm.api_key == "user_test_123"
    assert cfg.llm.api_key_env == "COMMAND_CODE_API_KEY"


def test_openai_resolves_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-123")
    monkeypatch.delenv("COMMAND_CODE_API_KEY", raising=False)
    p = tmp_path / "app.yaml"
    p.write_text(
        """
llm:
  enabled: true
  default:
    provider: openai
    model: gpt-4o-mini
    api_key_env: OPENAI_API_KEY
embed: {kind: hash}
"""
    )
    from onto3gpp.app_config import load_app_config

    cfg = load_app_config(p)
    assert cfg.llm.provider == "openai"
    assert cfg.llm.api_key == "sk-openai-123"


def test_ollama_no_key_even_if_env_set(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "should-not-be-used")
    p = tmp_path / "app.yaml"
    p.write_text(
        """
llm:
  enabled: true
  default:
    provider: ollama
    model: llama3
    api_base: http://localhost:11434
embed:
  kind: ollama
  api_base: http://localhost:11434
  model: embeddinggemma:300m
  dim: 768
"""
    )
    from onto3gpp.app_config import load_app_config

    cfg = load_app_config(p)
    assert cfg.llm.provider == "ollama"
    assert cfg.llm.api_key is None
    assert cfg.embed.kind == "ollama"
    assert cfg.embed.api_key is None


def test_explicit_api_key_overrides_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "env-key")
    p = tmp_path / "app.yaml"
    p.write_text(
        """
llm:
  enabled: true
  default:
    provider: cmdc
    model: minimax/minimax-m3-free
    api_key: explicit-hard
    api_key_env: COMMAND_CODE_API_KEY
embed: {kind: hash}
"""
    )
    from onto3gpp.app_config import load_app_config
    from onto3gpp.llm import _resolve_api_key

    # App loader keeps explicit; resolver prefers explicit
    cfg = load_app_config(p)
    assert cfg.llm.api_key == "explicit-hard"
    assert _resolve_api_key("explicit-hard", "COMMAND_CODE_API_KEY") == "explicit-hard"


def test_per_task_inherits_api_key_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "tok-xyz")
    p = tmp_path / "app.yaml"
    p.write_text(
        """
llm:
  enabled: true
  default:
    provider: cmdc
    model: minimax/minimax-m3-free
    api_base: https://api.commandcode.ai/provider/v1
    api_key_env: COMMAND_CODE_API_KEY
  models:
    judge: {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY}
    merge: {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY}
embed: {kind: hash}
"""
    )
    from onto3gpp.app_config import load_app_config

    cfg = load_app_config(p)
    assert cfg.llm.models["judge"].api_key == "tok-xyz"
    assert cfg.llm.models["merge"].api_key == "tok-xyz"


def test_resolver_fallback_chain(monkeypatch):
    from onto3gpp.llm import _resolve_api_key

    monkeypatch.delenv("COMMAND_CODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-123")
    assert _resolve_api_key(None, None) == "sk-openai-123"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert _resolve_api_key(None, None) is None
