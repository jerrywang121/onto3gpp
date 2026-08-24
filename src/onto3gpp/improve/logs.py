"""Search-log collection + offline analysis (Stage 4).

The improvement loop needs *evidence* of where retrieval fails. This module
collects search logs (queries + what was clicked) and analyzes them offline
to surface findings the LLM can act on:

- **missed terms**: query tokens that aren't ontology concepts (candidate
  new terms/aliases).
- **mismatches**: a clicked clause that wasn't in the top results (retrieval
  gap).
- **co-occurrences**: terms that frequently appear together in queries
  (candidate relations).

This is the deterministic, AI-free evidence layer feeding the AI-as-judge
improvement loop.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from onto3gpp.evaluate import GoldQuery
from onto3gpp.ontology.schema import Ontology
from onto3gpp.search.bm25 import BM25Index


@dataclass
class SearchLog:
    """A single logged search interaction."""

    query: str
    top_clauses: list[str] = field(default_factory=list)
    clicked_clause: str | None = None


def record_log(path: Path, log: SearchLog) -> None:
    """Append a search log to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(log.__dict__) + "\n")


def load_logs(path: Path) -> list[SearchLog]:
    """Load search logs from a JSONL file."""
    logs: list[SearchLog] = []
    if not path.exists():
        return logs
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        logs.append(
            SearchLog(
                query=data.get("query", ""),
                top_clauses=data.get("top_clauses", []),
                clicked_clause=data.get("clicked_clause"),
            )
        )
    return logs


def collect_logs(index: BM25Index, gold: list[GoldQuery], out: Path) -> int:
    """Run a gold set through an index and record search logs.

    For each gold query, the top-k clauses are logged, and the first relevant
    clause (if any) is treated as the "clicked" clause. Returns the number of
    logs written.
    """
    from onto3gpp.search.chunker import Chunk  # noqa: F401  (type only)

    count = 0
    for gq in gold:
        results = index.search(gq.query, top_k=10)
        top = [r.chunk.clause for r in results]
        relevant = set(gq.relevant_clauses)
        clicked = next((c for c in top if c in relevant), None)
        record_log(
            out,
            SearchLog(query=gq.query, top_clauses=top, clicked_clause=clicked),
        )
        count += 1
    return count


def _query_tokens(query: str) -> list[str]:
    """Lowercase alphanumeric tokens of a query.

    Underscores are preserved so 3GPP terms like ``RRC_CONNECTED`` or
    ``SIB1`` stay a single token (``rrc_connected``) rather than being split.
    """
    import re

    return re.findall(r"[a-z0-9_]+", query.lower())


def analyze_logs(logs: list[SearchLog], onto: Ontology) -> dict:
    """Analyze search logs and return findings the LLM can act on.

    Returns a dict with keys:
    - ``missed_terms``: query tokens that aren't ontology concepts.
    - ``mismatches``: clicked clauses that weren't in the top results.
    - ``cooccurrences``: frequent term pairs in queries.
    """
    concept_surfaces = {c.canonical.lower() for c in onto.concepts}
    for c in onto.concepts:
        concept_surfaces.update(a.lower() for a in c.aliases)

    missed: set[str] = set()
    mismatches: set[str] = set()
    cooccur: dict[tuple[str, str], int] = {}

    for log in logs:
        tokens = _query_tokens(log.query)
        for t in tokens:
            if t not in concept_surfaces:
                missed.add(t)
        # co-occurrence of every pair of non-stopword tokens
        for i in range(len(tokens)):
            for j in range(i + 1, len(tokens)):
                a, b = tokens[i], tokens[j]
                if a == b:
                    continue
                key = tuple(sorted((a, b)))
                cooccur[key] = cooccur.get(key, 0) + 1
        if log.clicked_clause and log.clicked_clause not in log.top_clauses:
            mismatches.add(log.clicked_clause)

    return {
        "missed_terms": sorted(missed),
        "mismatches": sorted(mismatches),
        "cooccurrences": sorted(
            (a, b) for (a, b), n in cooccur.items() if n >= 2
        ),
    }
