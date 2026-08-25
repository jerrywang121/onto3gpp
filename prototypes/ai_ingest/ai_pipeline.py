# prototypes/ai_ingest/ai_pipeline.py
"""Parallel pipeline primitives for AI-assisted ingestion (prototype).

A ModelQueue owns one worker thread per unique provider+model endpoint. The
three AI stages (extract/verify/relations) each use a different model, so
running them on separate queues lets the pipeline process multiple chunks
concurrently, one per stage.
"""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future

from ai_helpers import complete_json


class ModelQueue:
    """One worker thread per model endpoint; submit() returns a Future."""

    def __init__(self, key: str, config, max_tokens: int = 2048,
                 maxsize: int = 4):
        self.key = key
        self.config = config
        self.max_tokens = max_tokens
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._futures: dict[int, Future] = {}
        self._lock = threading.Lock()
        self._seq = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def submit(self, prompt: str, *, max_tokens: int = 2048,
               temperature: float = 0.1, attempts: int = 10,
               retries: list | None = None) -> Future:
        fut = Future()
        with self._lock:
            self._seq += 1
            job_id = self._seq
            self._futures[job_id] = fut
        self._queue.put((job_id, prompt, max_tokens, temperature, attempts,
                         retries))
        return fut

    def _run(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                break
            job_id, prompt, max_tokens, temperature, attempts, retries = job
            fut = self._futures.pop(job_id)
            try:
                result = complete_json(
                    prompt, self.config.model,
                    max_tokens=max_tokens, temperature=temperature,
                    attempts=attempts, config=self.config, retries=retries,
                )
                fut.set_result(result)
            except Exception as e:  # noqa: BLE001
                fut.set_exception(e)

    def shutdown(self) -> None:
        self._queue.put(None)
        self._thread.join(timeout=5)
