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


def complete_json(
    prompt: str,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    attempts: int = 10,
) -> dict:
    """Call the model with retries until a valid JSON object is returned."""
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            resp = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                api_base=API_BASE,
                custom_llm_provider=PROVIDER,
            )
            content = resp.choices[0].message.content
            if not content:
                continue
            data = json.loads(_extract_json(content))
            if isinstance(data, dict):
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
    raise RuntimeError(f"all {attempts} attempts failed: {last_err}")


def complete_json_array(
    prompt: str,
    model: str,
    max_tokens: int = 1024,
    temperature: float = 0.1,
    attempts: int = 10,
) -> list:
    """Call the model with retries until a valid JSON array is returned."""
    last_err: Exception | None = None
    for _ in range(attempts):
        try:
            resp = litellm.completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                api_base=API_BASE,
                custom_llm_provider=PROVIDER,
            )
            content = resp.choices[0].message.content
            if not content:
                continue
            data = json.loads(_extract_json(content))
            if isinstance(data, list):
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
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
