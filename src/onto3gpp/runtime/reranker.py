"""Relationship-aware reranker (Stage 2).

Deterministic, CPU-only reranking of BM25 results using the ontology graph.
Given a query, resolve the concepts it mentions and boost chunks that mention
related concepts (1-hop neighbors). This surfaces results that are
semantically related to the query even when they don't share exact tokens.

The reranker is domain-agnostic — it operates on the ontology graph.
"""

from __future__ import annotations

from onto3gpp.ontology.schema import Ontology
from onto3gpp.runtime.reasoner import reason
from onto3gpp.search.bm25 import SearchResult


def rerank(
    results: list[SearchResult],
    query: str,
    onto: Ontology,
    boost: float = 0.2,
) -> list[SearchResult]:
    """Rerank BM25 results, boosting chunks that mention concepts related to
    the query's concepts.

    The boost is added to the BM25 score of any result whose chunk text
    mentions a related concept (a 1-hop neighbor of a query concept). Results
    are then re-sorted by the boosted score, stable for ties.
    """
    if not results:
        return []

    plan = reason(query, onto)
    related = set(plan.related_terms)

    if not related:
        return results

    boosted: list[SearchResult] = []
    for r in results:
        text_lower = r.chunk.text.lower()
        score = r.score
        for term in related:
            if term.lower() in text_lower:
                score += boost
        boosted.append(SearchResult(chunk=r.chunk, score=score))

    # stable sort by boosted score (descending)
    boosted.sort(key=lambda r: r.score, reverse=True)
    return boosted
