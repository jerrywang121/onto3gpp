"""Relationship + structure-aware reranker (Stage 2/3).

Deterministic, CPU-only reranking of BM25 results using the ontology graph and
document structure. Given a query, resolve the concepts it mentions and boost
chunks that mention related concepts (1-hop neighbors). Additionally, boost
chunks whose clause title or ancestor titles match the query (structure-aware
boost). This surfaces results that are semantically related to the query even
when they don't share exact tokens.

The reranker is domain-agnostic — it operates on the ontology graph and the
clause/title structure of chunks.
"""

from __future__ import annotations

from onto3gpp.ontology.schema import Ontology
from onto3gpp.runtime.reasoner import reason
from onto3gpp.runtime.structure import structure_boost
from onto3gpp.search.bm25 import SearchResult
from onto3gpp.search.chunker import Chunk


def rerank(
    results: list[SearchResult],
    query: str,
    onto: Ontology,
    chunks: list[Chunk] | None = None,
    boost: float = 0.2,
    structure_boost_amount: float = 0.3,
) -> list[SearchResult]:
    """Rerank BM25 results, boosting chunks that mention concepts related to
    the query's concepts, and chunks whose title/ancestor titles match the
    query.

    The relationship boost is added to the BM25 score of any result whose
    chunk text mentions a related concept (a 1-hop neighbor of a query
    concept). The structure boost is added to any result whose clause title or
    ancestor titles share a token with the query. Results are then re-sorted
    by the boosted score, stable for ties.

    ``chunks`` is the full chunk list used for structure-aware boosting (to
    look up ancestor titles). If ``None``, only the relationship boost is
    applied.
    """
    if not results:
        return []

    plan = reason(query, onto)
    related = set(plan.related_terms)

    boosted: list[SearchResult] = []
    for r in results:
        text_lower = r.chunk.text.lower()
        score = r.score
        if related:
            for term in related:
                if term.lower() in text_lower:
                    score += boost
        boosted.append(SearchResult(chunk=r.chunk, score=score))

    if chunks is not None:
        boosted = structure_boost(boosted, query, chunks, boost=structure_boost_amount)

    # stable sort by boosted score (descending)
    boosted.sort(key=lambda r: r.score, reverse=True)
    return boosted
