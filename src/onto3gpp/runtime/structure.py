"""Structure-aware boosts (Stage 3).

Deterministic, CPU-only boosting of search results based on document
structure. A chunk's clause title and its ancestor titles (the titles of the
clauses it nests under) carry strong relevance signal that the chunk body text
may not. For example, a query about "handover" should surface the clause
titled "Handover" (9.2.3.2) and its children even when their body text doesn't
contain the word "handover".

The boost is domain-agnostic — it operates on the clause/title structure of
chunks, not on domain terms.
"""

from __future__ import annotations

from onto3gpp.search.bm25 import SearchResult, tokenize
from onto3gpp.search.chunker import Chunk


def _ancestors_of(clause: str) -> list[str]:
    """Return the ancestor clause numbers of a dotted clause, outermost first."""
    parts = clause.split(".")
    if len(parts) <= 1:
        return []
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def build_ancestor_map(chunks: list[Chunk]) -> dict[str, list[str]]:
    """Map each chunk's clause to its ancestor clause numbers.

    Returns ``{clause: [ancestor_clause, ...]}`` where ancestors are ordered
    outermost-first. Chunks with the same clause share the same ancestor list.
    """
    amap: dict[str, list[str]] = {}
    for c in chunks:
        if c.clause not in amap:
            amap[c.clause] = _ancestors_of(c.clause)
    return amap


def _title_tokens(chunk: Chunk, amap: dict[str, list[str]], chunks_by_clause: dict[str, Chunk]) -> set[str]:
    """Return the set of tokens in a chunk's title and its ancestors' titles."""
    tokens: set[str] = set()
    for clause in [chunk.clause] + amap.get(chunk.clause, []):
        title = chunks_by_clause.get(clause)
        if title is not None:
            tokens.update(tokenize(title.title))
    return tokens


def structure_boost(
    results: list[SearchResult],
    query: str,
    chunks: list[Chunk],
    boost: float = 0.3,
) -> list[SearchResult]:
    """Boost results whose clause title or ancestor titles match the query.

    For each result, compute the set of tokens in its title + ancestor titles.
    If any of those tokens appears in the query, add ``boost`` to the score.
    Results are re-sorted by the boosted score, stable for ties.

    ``chunks`` is the full chunk list (used to look up ancestor titles by
    clause). ``boost`` is the per-match score increment.
    """
    if not results:
        return []

    amap = build_ancestor_map(chunks)
    chunks_by_clause: dict[str, Chunk] = {}
    for c in chunks:
        if c.clause not in chunks_by_clause:
            chunks_by_clause[c.clause] = c

    q_tokens = set(tokenize(query))
    if not q_tokens:
        return results

    boosted: list[SearchResult] = []
    for r in results:
        title_tokens = _title_tokens(r.chunk, amap, chunks_by_clause)
        overlap = q_tokens & title_tokens
        score = r.score + (boost if overlap else 0.0)
        boosted.append(SearchResult(chunk=r.chunk, score=score))

    boosted.sort(key=lambda r: r.score, reverse=True)
    return boosted
