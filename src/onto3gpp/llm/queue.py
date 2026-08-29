"""ModelQueue — one worker thread per provider+model endpoint.

Mirrors ``prototypes/ai_ingest/ai_pipeline.py:ModelQueue`` but is
provider-agnostic and lives in the app package so ``ingest_v2 --parallel``
and future stages can reuse it. Each queue owns a single worker thread that
serializes calls to one LLM endpoint; different provider+model combos get
different queues and thus run concurrently.

See ``prototypes/ai_ingest/ai_pipeline.py`` for the prototype origin and
``prototypes/ai-ingest-v2/README.md`` for the v2 pipeline that uses it.
"""

from __future__ import annotations

import json
import queue
import re
import threading
import time
from concurrent.futures import Future
from typing import Any

from onto3gpp.llm import LLMClient, LLMConfig


def _extract_json(text: str) -> dict:
    """Extract a JSON object from an LLM response (handles code fences)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if fence:
        t = fence.group(1).strip()
    # Find first balanced {...}
    start = t.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    end = -1
    for i in range(start, len(t)):
        if t[i] == "{":
            depth += 1
        elif t[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    if end == -1:
        raise ValueError("unbalanced JSON")
    return json.loads(t[start : end + 1])


class ModelQueue:
    """One worker thread per model endpoint; ``submit()`` returns a ``Future``.

    ``config`` is an ``LLMConfig`` (from ``config/app.yaml``). The queue
    serializes calls to that endpoint; callers submit prompts and await
    ``Future.result()``. Different queues (different provider+model) run in
    parallel. When ``config.enabled`` is false the worker immediately fails
    futures with ``LLMDisabledError`` so callers can fall back deterministically.

    ``maxsize`` bounds the pending queue; ``submit`` blocks if full (backpressure).
    """

    def __init__(self, key: str, config: LLMConfig, maxsize: int = 8) -> None:
        self.key = key
        self.config = config
        self.client = LLMClient(config)
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._futures: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        attempts: int = 5,
        retries: list | None = None,
        is_json: bool = False,
    ) -> Future:
        """Enqueue a prompt. Returns a ``Future`` whose result is ``str`` (or ``dict`` if ``is_json``).

        ``retries`` is an optional list to which the number of attempts taken is appended.
        """
        fut: Future = Future()
        with self._lock:
            self._seq += 1
            job_id = self._seq
            self._futures[job_id] = fut
        # Capture per-call overrides if given; otherwise use config values.
        self._queue.put((job_id, prompt, max_tokens, temperature, attempts, retries, is_json))
        return fut

    def submit_json(
        self,
        prompt: str,
        *,
        max_tokens: int | None = None,
        temperature: float | None = None,
        attempts: int = 5,
        retries: list | None = None,
    ) -> Future:
        """Shorthand for ``submit(..., is_json=True)`` — result is a ``dict``."""
        return self.submit(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            attempts=attempts,
            retries=retries,
            is_json=True,
        )

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            job_id, prompt, max_tokens, temperature, attempts, retries, is_json = job
            fut = self._futures.pop(job_id, None)
            if fut is None:
                continue
            # Temporarily override config for this call if requested.
            orig_max = self.config.max_tokens
            orig_temp = self.config.temperature
            if max_tokens is not None:
                self.config.max_tokens = max_tokens
            if temperature is not None:
                self.config.temperature = temperature
            try:
                result = self._call_with_retries(prompt, attempts=attempts, retries=retries, is_json=is_json)
                fut.set_result(result)
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)
            finally:
                self.config.max_tokens = orig_max
                self.config.temperature = orig_temp

    def _call_with_retries(self, prompt: str, attempts: int = 5, retries: list | None = None, is_json: bool = False) -> Any:
        last_err: Exception | None = None
        for n in range(1, attempts + 1):
            try:
                text = self.client.complete(prompt)
                if not text:
                    last_err = RuntimeError("empty response")
                    time.sleep(0.05)
                    continue
                if is_json:
                    data = _extract_json(text)
                    if not isinstance(data, dict):
                        last_err = ValueError(f"expected JSON object, got {type(data)}")
                        time.sleep(0.05)
                        continue
                    if retries is not None:
                        retries.append(n)
                    return data
                else:
                    if retries is not None:
                        retries.append(n)
                    return text
            except Exception as e:  # noqa: BLE001
                last_err = e
                time.sleep(0.05)
        if retries is not None:
            retries.append(attempts)
        raise RuntimeError(f"all {attempts} attempts failed for {self.key}: {last_err}")

    def shutdown(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)
