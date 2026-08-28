"""Configurable LLM client abstraction (external AI hooks).

This is the seam where the app can plug in external AI models. The pipeline
itself is deterministic and AI-free; these hooks are *optional* and enabled
only when app config (``config/app.yaml``) configures an LLM.

The client wraps LiteLLM (``litellm.completion``), which supports OpenAI,
Anthropic, local vLLM/ollama, and many other providers behind one interface.
A subclass can override :meth:`_call` to use any other backend.

Configuration lives in the app config ``config/app.yaml`` under ``llm:``::

    llm:
      enabled: false
      default:
        provider: openai
        model: gpt-4o-mini
        api_key_env: OPENAI_API_KEY
      models:
        merge: {provider: ollama, model: llama3, api_base: http://localhost:11434}

Domain packs no longer own ``llm:`` (ADR-0015); they stay portable.

Each entry may declare ``api_key_env: <ENV_NAME>`` (e.g. ``COMMAND_CODE_API_KEY``
for ``cmdc``, ``OPENAI_API_KEY`` for ``openai``; omit for ``ollama``/local).
The loader resolves ``api_key`` as: explicit ``api_key`` → ``os.getenv(api_key_env)``
→ legacy fallback (``COMMAND_CODE_API_KEY``/``OPENAI_API_KEY``) when
``api_key_env`` is unset (backward compat).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any


def _resolve_api_key(explicit: str | None, api_key_env: str | None = None) -> str | None:
    if explicit:
        return explicit
    if api_key_env:
        return os.getenv(api_key_env) or None
    # Legacy fallback for old configs without api_key_env (backward compat).
    return (
        os.getenv("COMMAND_CODE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("COMMANDCODE_API_KEY")
    )


class LLMDisabledError(RuntimeError):
    """Raised when an LLM call is attempted but the client is disabled."""


@dataclass
class LLMConfig:
    """Configuration for external AI models (multi-model routing, ADR-0012).

    Supports a ``default`` model plus a ``models`` map of named task→model
    configs. A task with no explicit entry falls back to ``default``. The
    flat single-model form (``model``/``provider``/``api_base``/``api_key``)
    is treated as ``default`` for backward compatibility.

    ``api_key_env`` names the env var that carries the secret (e.g.
    ``COMMAND_CODE_API_KEY`` for ``cmdc``, ``OPENAI_API_KEY`` for ``openai``;
    omit for ``ollama``). The actual key never lives in YAML.
    """

    enabled: bool = False
    model: str = "gpt-4o-mini"
    provider: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    extra: dict[str, Any] = field(default_factory=dict)
    models: dict[str, LLMConfig] = field(default_factory=dict)

    @property
    def default(self) -> LLMConfig:
        """The default model config (this config, minus the models map)."""
        return LLMConfig(
            enabled=self.enabled,
            model=self.model,
            provider=self.provider,
            api_base=self.api_base,
            api_key=self.api_key,
            api_key_env=self.api_key_env,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            extra=dict(self.extra),
        )

    @classmethod
    def from_dict(cls, data: dict | None) -> LLMConfig:
        """Build an LLMConfig from a dict, ignoring unknown keys.

        Supports both the flat single-model form and the multi-model form
        (``default`` + ``models`` map).
        """
        if not data:
            return cls()
        known = {
            "enabled",
            "model",
            "provider",
            "api_base",
            "api_key",
            "api_key_env",
            "temperature",
            "max_tokens",
        }
        # Multi-model form: a `default` dict and/or a `models` map.
        if "default" in data or "models" in data:
            enabled = data.get("enabled", False)
            default = cls.from_dict(data.get("default"))
            default.enabled = enabled
            # Inherit api_base/api_key/api_key_env from default into tasks that omit them
            # (so they don't need to be repeated per task).
            if default.api_base:
                default.extra.setdefault("api_base", default.api_base)
            if default.api_key:
                default.extra.setdefault("api_key", default.api_key)
            if default.api_key_env:
                default.extra.setdefault("api_key_env", default.api_key_env)
            models = {
                name: cls.from_dict(cfg) for name, cfg in data.get("models", {}).items()
            }
            for cfg in models.values():
                cfg.enabled = enabled
                # Inherit provider if omitted; only inherit wiring fields
                # when the effective provider matches the default's provider
                # (so an ollama task doesn't pick up COMMAND_CODE_API_KEY).
                if not cfg.provider and default.provider:
                    cfg.provider = default.provider
                same_provider = cfg.provider == default.provider
                if same_provider:
                    if not cfg.api_base and default.api_base:
                        cfg.api_base = default.api_base
                    if not cfg.api_key and default.api_key:
                        cfg.api_key = default.api_key
                    if not cfg.api_key_env and default.api_key_env:
                        cfg.api_key_env = default.api_key_env
            default.models = models
            return default
        # Flat single-model form.
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extra=extra)


def _extract_json(text: str) -> dict:
    """Extract a JSON object from an LLM response (handles code fences)."""
    text = text.strip()
    # Strip markdown code fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return json.loads(text)


class LLMClient:
    """A thin, swappable wrapper around an external AI model.

    Subclasses override :meth:`_call` to talk to a specific backend. The
    default implementation uses LiteLLM.
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    def _call(self, prompt: str) -> str:
        """Send a prompt and return the raw text response."""
        import litellm

        # Map non-litellm provider names (e.g. "cmdc" — an internal alias for
        # an OpenAI-compatible gateway) to a real litellm provider. The model
        # name may already carry a prefix like "openai/..."; we normalize it.
        provider = self.config.provider
        model = self.config.model
        KNOWN_OPENAI_COMPAT = {"cmdc", "commandcode"}
        if provider in KNOWN_OPENAI_COMPAT:
            provider = "openai"
            if not model.startswith("openai/"):
                model = f"openai/{model}"

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        api_key = _resolve_api_key(self.config.api_key, self.config.api_key_env)
        if api_key:
            kwargs["api_key"] = api_key
        if provider:
            kwargs["custom_llm_provider"] = provider
        kwargs.update(self.config.extra)
        resp = litellm.completion(**kwargs)
        return resp.choices[0].message.content

    def complete(self, prompt: str) -> str:
        """Complete a prompt, raising :class:`LLMDisabledError` if disabled."""
        if not self.config.enabled:
            raise LLMDisabledError("LLM client is disabled in domain config")
        return self._call(prompt)

    def complete_json(self, prompt: str) -> dict:
        """Complete a prompt and parse the response as a JSON object."""
        return _extract_json(self.complete(prompt))

    def for_task(self, task: str) -> LLMClient:
        """Return a client bound to the model config for ``task``.

        Resolves the task's model from ``config.models``; falls back to the
        ``default`` model if the task has no explicit entry. The returned
        client shares the same backend class (``type(self)``) so subclasses
        keep their custom ``_call``.
        """
        cfg = self.config.models.get(task, self.config.default)
        return type(self)(cfg)
