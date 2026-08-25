"""Tests for the CLI --llm-model override helper (Stage 8)."""

from onto3gpp.cli import _apply_llm_overrides
from onto3gpp.llm import LLMConfig


def test_apply_llm_overrides_task_and_default():
    cfg = LLMConfig.from_dict(
        {
            "enabled": True,
            "default": {"model": "gpt-4o-mini"},
            "models": {"judge": {"model": "gpt-4o"}},
        }
    )
    out = _apply_llm_overrides(cfg, "judge=gpt-4o-turbo,default=gpt-4o-mini")
    assert out.models["judge"].model == "gpt-4o-turbo"
    assert out.model == "gpt-4o-mini"


def test_apply_llm_overrides_adds_new_task():
    cfg = LLMConfig.from_dict({"enabled": True, "default": {"model": "gpt-4o-mini"}})
    out = _apply_llm_overrides(cfg, "extract=llama3")
    assert out.models["extract"].model == "llama3"
    assert out.model == "gpt-4o-mini"


def test_apply_llm_overrides_preserves_enabled():
    cfg = LLMConfig.from_dict({"enabled": True, "default": {"model": "gpt-4o-mini"}})
    out = _apply_llm_overrides(cfg, "judge=gpt-4o")
    assert out.enabled is True
