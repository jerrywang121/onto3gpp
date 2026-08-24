"""Configurable LLM client abstraction (external AI hooks).

This is the seam where the app can plug in external AI models. The pipeline
itself is deterministic and AI-free; these hooks are *optional* and enabled
only when a domain pack configures an LLM.

The client wraps LiteLLM (``litellm.completion``), which supports OpenAI,
Anthropic, local vLLM/ollama, and many other providers behind one interface.
A subclass can override :meth:`_call` to use any other backend.

Configuration lives in the domain pack's ``config.yaml`` under ``llm:``::

    llm:
      enabled: false
      model: gpt-4o-mini
      provider: openai
      api_base: null
      temperature: 0.0
      max_tokens: 1024
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


class LLMDisabledError(RuntimeError):
    """Raised when an LLM call is attempted but the client is disabled."""


@dataclass
class LLMConfig:
    """Configuration for an external AI model."""

    enabled: bool = False
    model: str = "gpt-4o-mini"
    provider: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    temperature: float = 0.0
    max_tokens: int = 1024
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict | None) -> LLMConfig:
        """Build an LLMConfig from a dict, ignoring unknown keys."""
        if not data:
            return cls()
        known = {
            "enabled",
            "model",
            "provider",
            "api_base",
            "api_key",
            "temperature",
            "max_tokens",
        }
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

        kwargs: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        if self.config.provider:
            kwargs["custom_llm_provider"] = self.config.provider
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
