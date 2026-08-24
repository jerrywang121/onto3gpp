"""BM25 lexical search index.

Stage 0 baseline: a simple BM25 index over chunks. Uses `rank_bm25`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from onto3gpp.search.chunker import Chunk

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase and split text into alphanumeric tokens."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class SearchResult:
    """A ranked search result."""

    chunk: Chunk
    score: float


class BM25Index:
    """A BM25 index over a list of chunks."""

    def __init__(self, chunks: list[Chunk], bm25: BM25Okapi) -> None:
        self.chunks = chunks
        self.bm25 = bm25

    @classmethod
    def build(cls, chunks: list[Chunk]) -> "BM25Index":
        """Build an index from chunks."""
        tokenized = [tokenize(c.text) for c in chunks]
        bm25 = BM25Okapi(tokenized)
        return cls(chunks, bm25)

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Return the top-k chunks for a query, ranked by BM25 score."""
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = self.bm25.get_scores(q_tokens)
        ranked = sorted(
            range(len(self.chunks)),
            key=lambda i: scores[i],
            reverse=True,
        )
        results = [
            SearchResult(chunk=self.chunks[i], score=scores[i])
            for i in ranked
            if scores[i] > 0
        ]
        return results[:top_k]

    def search_expanded(
        self, query: str, dictionary, top_k: int = 10
    ) -> list[SearchResult]:
        """Search with query expansion via a compiled dictionary.

        The query is expanded with canonical terms found by runtime NER, so
        abbreviations and aliases match their canonical surface forms in the
        index.
        """
        from onto3gpp.runtime.ner import expand_query

        q_tokens = expand_query(dictionary, query)
        if not q_tokens:
            return []
        scores = self.bm25.get_scores(q_tokens)
        ranked = sorted(
            range(len(self.chunks)),
            key=lambda i: scores[i],
            reverse=True,
        )
        results = [
            SearchResult(chunk=self.chunks[i], score=scores[i])
            for i in ranked
            if scores[i] > 0
        ]
        return results[:top_k]

    def search_ontology(
        self, query: str, onto, top_k: int = 10
    ) -> list[SearchResult]:
        """Search with ontology-aware candidate generation.

        The query is scored with plain BM25 (so the query's own signal is not
        polluted by expansion terms). Chunks that mention a related concept
        (a 1-hop neighbor of a query concept) are added to the candidate set
        with a floor score, so the relationship-aware reranker can boost them
        into the top-k even when they share no exact tokens with the query.
        """
        from onto3gpp.runtime.reasoner import reason

        plan = reason(query, onto)
        q_tokens = tokenize(query)
        if not q_tokens:
            return []
        scores = self.bm25.get_scores(q_tokens)
        related = set(plan.related_terms)

        candidates: list[SearchResult] = []
        for i, chunk in enumerate(self.chunks):
            s = scores[i]
            if s > 0:
                candidates.append(SearchResult(chunk=chunk, score=s))
                continue
            # chunk doesn't match the query lexically; keep it as a candidate
            # only if it mentions a related concept (floor score so it isn't
            # filtered out before the reranker can boost it)
            text_lower = chunk.text.lower()
            if any(t.lower() in text_lower for t in related):
                candidates.append(SearchResult(chunk=chunk, score=1e-6))

        candidates.sort(key=lambda r: r.score, reverse=True)
        return candidates[:top_k]
