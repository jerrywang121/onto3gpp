"""Eval harness: run a gold set against an index and compute metrics.

A gold query maps a query string to a set of relevant clause IDs. The harness
runs each query through the search index, checks whether the relevant clauses
appear in the top-k results, and aggregates MRR / NDCG@k / Recall@k.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from onto3gpp.evaluate.metrics import mrr, ndcg_at_k, recall_at_k
from onto3gpp.search.bm25 import BM25Index


@dataclass
class GoldQuery:
    """A single gold query: text + set of relevant clause IDs.

    `spec` optionally scopes the query to a single spec (e.g. "38300"). When
    set, the query is evaluated against an index built only from that spec's
    chunks, so other specs' chunks don't dilute the gold-relevant results.
    """

    query: str
    relevant_clauses: list[str]
    spec: str = ""


@dataclass
class EvalResult:
    """Aggregated evaluation metrics over a gold set."""

    mrr: float
    ndcg_at_10: float
    recall_at_5: float
    recall_at_10: float
    num_queries: int
    per_query: list[dict] = field(default_factory=list)


def load_gold(path: Path) -> list[GoldQuery]:
    """Load gold queries from a JSONL file (one query per line)."""
    queries: list[GoldQuery] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        queries.append(
            GoldQuery(
                query=data["query"],
                relevant_clauses=data["relevant_clauses"],
                spec=data.get("spec", ""),
            )
        )
    return queries


def evaluate(
    index: BM25Index,
    gold: list[GoldQuery],
    top_k: int = 10,
    dictionary=None,
    ontology=None,
) -> EvalResult:
    """Evaluate an index against a gold set.

    If `dictionary` is provided, queries are expanded with canonical terms
    (term-expanded search); otherwise plain BM25 is used. If `ontology` is
    provided, results are reranked with the relationship-aware reranker.
    """
    from onto3gpp.runtime.reranker import rerank

    mrr_scores: list[float] = []
    ndcg_scores: list[float] = []
    recall5_scores: list[float] = []
    recall10_scores: list[float] = []
    per_query: list[dict] = []

    for gq in gold:
        if ontology is not None:
            results = index.search_ontology(gq.query, ontology, top_k=top_k)
        elif dictionary is not None:
            results = index.search_expanded(gq.query, dictionary, top_k=top_k)
        else:
            results = index.search(gq.query, top_k=top_k)
        if ontology is not None:
            results = rerank(results, gq.query, ontology)
        relevant = set(gq.relevant_clauses)
        # relevance label per result: 1 if the result's clause is relevant
        relevance = [1 if r.chunk.clause in relevant else 0 for r in results]
        total_relevant = len(relevant)

        mrr_scores.append(mrr(relevance))
        ndcg_scores.append(ndcg_at_k(relevance, k=top_k))
        recall5_scores.append(recall_at_k(relevance, k=5, total_relevant=total_relevant))
        recall10_scores.append(recall_at_k(relevance, k=10, total_relevant=total_relevant))

        per_query.append(
            {
                "query": gq.query,
                "mrr": mrr(relevance),
                "top_clauses": [r.chunk.clause for r in results[:5]],
            }
        )

    n = len(gold)
    return EvalResult(
        mrr=sum(mrr_scores) / n if n else 0.0,
        ndcg_at_10=sum(ndcg_scores) / n if n else 0.0,
        recall_at_5=sum(recall5_scores) / n if n else 0.0,
        recall_at_10=sum(recall10_scores) / n if n else 0.0,
        num_queries=n,
        per_query=per_query,
    )
