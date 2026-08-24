"""IR metrics for the eval harness.

Standard metrics: MRR, NDCG@k, Recall@k. These operate on a list of binary
relevance labels (1 = relevant, 0 = not) in ranked order.
"""

from __future__ import annotations

import math


def mrr(relevance: list[int]) -> float:
    """Mean Reciprocal Rank: 1/rank of the first relevant result, else 0."""
    for i, rel in enumerate(relevance):
        if rel:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(relevance: list[int], k: int, total_relevant: int) -> float:
    """Recall@k: fraction of relevant results found in the top-k."""
    if total_relevant == 0:
        return 0.0
    found = sum(relevance[:k])
    return found / total_relevant


def _dcg(relevance: list[int], k: int) -> float:
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(relevance[:k]))


def ndcg_at_k(relevance: list[int], k: int) -> float:
    """NDCG@k: normalized discounted cumulative gain."""
    ideal = sorted(relevance, reverse=True)
    dcg = _dcg(relevance, k)
    idcg = _dcg(ideal, k)
    if idcg == 0:
        return 0.0
    return dcg / idcg
