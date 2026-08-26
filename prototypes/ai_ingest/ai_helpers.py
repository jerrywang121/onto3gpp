"""Robust AI helpers for AI-assisted ingestion (prototype).

The local ollama models (deepseek-v4-flash, minimax-m3) are flaky: they
frequently return empty content or malformed JSON. This module wraps
litellm with retry + JSON extraction so the AI-assisted ingest can be
driven reliably.
"""

from __future__ import annotations

import json
import re
import time

import litellm

API_BASE = "http://localhost:11434"
PROVIDER = "ollama"


def _strip_json(text: str) -> str:
    """Strip code fences and a leading 'json' marker from an LLM response."""
    t = text.strip()
    if t.startswith("json"):
        t = t[4:].strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    return t


def _resolve_call_kwargs(
    model: str,
    max_tokens: int,
    temperature: float,
    config=None,
) -> dict:
    """Build litellm kwargs, preferring an LLMConfig when provided.

    ``config`` may be an ``onto3gpp.llm.LLMConfig`` (from the domain pack's
    config.yaml). When given, its model/provider/api_base/temperature/
    max_tokens override the positional defaults. This lets the prototype read
    per-task model routing from config.yaml instead of hard-coding ollama.
    """
    if config is not None:
        model = config.model
        temperature = config.temperature
        max_tokens = config.max_tokens
        provider = config.provider or PROVIDER
        api_base = config.api_base or API_BASE
    else:
        provider = PROVIDER
        api_base = API_BASE
    return {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "api_base": api_base,
        "custom_llm_provider": provider,
    }


def complete_json(
    prompt: str,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    attempts: int = 10,
    config=None,
    retries: list | None = None,
) -> dict:
    """Call the model with retries until a valid JSON object is returned.

    ``config`` (optional) is an ``onto3gpp.llm.LLMConfig``; when provided it
    overrides model/provider/api_base/temperature/max_tokens.

    ``retries`` (optional) is a list; the number of attempts taken is appended
    to it (1 = first try succeeded, >1 = retries happened). Used to monitor
    model reliability.
    """
    kwargs = _resolve_call_kwargs(model, max_tokens, temperature, config)
    last_err: Exception | None = None
    for n in range(1, attempts + 1):
        try:
            resp = litellm.completion(
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
            content = resp.choices[0].message.content
            if not content:
                continue
            data = json.loads(_extract_json(content))
            if isinstance(data, dict):
                if retries is not None:
                    retries.append(n)
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
    if retries is not None:
        retries.append(attempts)
    raise RuntimeError(f"all {attempts} attempts failed: {last_err}")


def complete_json_array(
    prompt: str,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    attempts: int = 10,
    config=None,
    retries: list | None = None,
) -> list:
    """Call the model with retries until a valid JSON array is returned.

    ``config`` (optional) is an ``LLMConfig``; when provided it overrides
    model/provider/api_base/temperature/max_tokens.

    ``retries`` (optional) is a list; the number of attempts taken is appended
    to it (1 = first try succeeded, >1 = retries happened).
    """
    kwargs = _resolve_call_kwargs(model, max_tokens, temperature, config)
    last_err: Exception | None = None
    for n in range(1, attempts + 1):
        try:
            resp = litellm.completion(
                messages=[{"role": "user", "content": prompt}],
                **kwargs,
            )
            content = resp.choices[0].message.content
            if not content:
                continue
            data = json.loads(_extract_json(content))
            if isinstance(data, list):
                if retries is not None:
                    retries.append(n)
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
    if retries is not None:
        retries.append(attempts)
    raise RuntimeError(f"all {attempts} attempts failed: {last_err}")


def _extract_json(text: str) -> str:
    """Extract the JSON substring from a response (handles fences + prose)."""
    t = text.strip()
    if t.startswith("json"):
        t = t[4:].strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    # If the whole thing is a JSON object, return it.
    if t.startswith("{") and t.endswith("}"):
        return t
    # Otherwise try to find the first balanced {...} block.
    start = t.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                return t[start : i + 1]
    raise ValueError("unbalanced JSON")
