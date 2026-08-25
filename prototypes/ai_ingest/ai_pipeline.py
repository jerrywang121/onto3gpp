# prototypes/ai_ingest/ai_pipeline.py
"""Parallel pipeline primitives for AI-assisted ingestion (prototype).

A ModelQueue owns one worker thread per unique provider+model endpoint. The
three AI stages (extract/verify/relations) each use a different model, so
running them on separate queues lets the pipeline process multiple chunks
concurrently, one per stage.
"""
from __future__ import annotations

import json
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


def run_pipeline(sections, dictionary, onto, queues, *, max_chars,
                 fallback_model, configs, dict_path, onto_path, log_path,
                 done, on_progress=None) -> dict:
    """Run the 3-stage pipeline with ordered apply. Returns aggregate stats."""
    from ai_progressive import (compute_snapshot, apply_result, save_dict,
                                save_ontology, EXTRACT_PROMPT_TEMPLATE,
                                VERIFY_PROMPT_TEMPLATE, RELATIONS_PROMPT_TEMPLATE,
                                CONCEPT_TYPES, VERIFY_CANDIDATE_CAP,
                                _fmt_known, _fmt_candidates, _fmt_relations)

    stats = {"ok": 0, "fail": 0, "terms_total": 0, "rels_total": 0,
             "chars_total": 0, "fb_extract": 0, "fb_verify": 0,
             "fb_relations": 0, "rt_extract": 0, "rt_verify": 0,
             "rt_relations": 0, "match_terms_total": 0,
             "match_rels_total": 0, "match_cands_total": 0}
    pending = {}  # index -> (section, snapshot, futures, retries)
    order = []    # indices in submission order
    applied = set()

    def _submit(index, section):
        snapshot = compute_snapshot(section, dictionary, onto, max_chars)
        retries = {"extract": [], "verify": [], "relations": []}
        f_extract = queues["extract"].submit(
            EXTRACT_PROMPT_TEMPLATE.format(text=snapshot["text"],
                                           types=CONCEPT_TYPES,
                                           known=_fmt_known(snapshot["known"])),
            max_tokens=2048, temperature=0.1, attempts=10,
            retries=retries["extract"])
        f_verify = queues["verify"].submit(
            VERIFY_PROMPT_TEMPLATE.format(text=snapshot["text"],
                                          candidates=_fmt_candidates(
                                              snapshot["candidates"],
                                              cap=VERIFY_CANDIDATE_CAP)),
            max_tokens=2048, temperature=0.1, attempts=5,
            retries=retries["verify"])
        f_relations = queues["relations"].submit(
            RELATIONS_PROMPT_TEMPLATE.format(text=snapshot["text"],
                                             known_relations=_fmt_relations(
                                                 snapshot["known_rels"]),
                                             candidate_relations=_fmt_relations(
                                                 snapshot["candidate_rels"])),
            max_tokens=2048, temperature=0.1, attempts=5,
            retries=retries["relations"])
        pending[index] = (section, snapshot, f_extract, f_verify,
                          f_relations, retries)
        order.append(index)

    def _apply_next():
        nonlocal dictionary, onto
        while order and order[0] in applied:
            order.pop(0)
        if not order:
            return
        index = order[0]
        section, snapshot, f_extract, f_verify, f_relations, retries = \
            pending[index]
        if not (f_extract.done() and f_verify.done() and f_relations.done()):
            return
        try:
            result = {}
            result.update(f_extract.result())
            result["_verify"] = f_verify.result()
            result["_relations"] = f_relations.result()
            result["_fallback"] = {"extract": False, "verify": False,
                                   "relations": False}
            result["_retries"] = {k: v[0] if v else 0
                                  for k, v in retries.items()}
            rt = result["_retries"]
            stats["rt_extract"] += rt.get("extract", 0)
            stats["rt_verify"] += rt.get("verify", 0)
            stats["rt_relations"] += rt.get("relations", 0)
            result["_match"] = {"known_terms": len(snapshot["known"]),
                                "known_relations": len(snapshot["known_rels"]),
                                "candidates": len(snapshot["candidates"])}
            result["_candidates"] = snapshot["candidates"]
            match = result["_match"]
            stats["match_terms_total"] += match["known_terms"]
            stats["match_rels_total"] += match["known_relations"]
            stats["match_cands_total"] += match["candidates"]
            stats["chars_total"] += min(len(section.text), max_chars)
            dictionary, onto, summary = apply_result(
                result, dictionary, onto, section, snapshot["candidates"])
            stats["terms_total"] += summary["terms_added"]
            stats["rels_total"] += summary["relations_added"]
            stats["ok"] += 1
            save_dict(dictionary, dict_path)
            save_ontology(onto, onto_path)
            # `_candidates` holds CandidateTerm objects (not JSON-serializable);
            # pop it before logging, mirroring the sequential path.
            result.pop("_candidates", None)
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"index": index, "clause": section.clause,
                                      "terms_added": summary["terms_added"],
                                      "relations_added": summary["relations_added"],
                                      "match": match, "result": result}) + "\n")
        except Exception as e:  # noqa: BLE001
            stats["fail"] += 1
            with log_path.open("a", encoding="utf-8") as log:
                log.write(json.dumps({"index": index, "clause": section.clause,
                                      "error": str(e), "result": {}}) + "\n")
        applied.add(index)
        pending.pop(index, None)
        order.pop(0)

    for index, section in enumerate(sections):
        if index in done:
            continue
        _submit(index, section)
        _apply_next()
    # drain remaining
    while order:
        _apply_next()
    return stats
