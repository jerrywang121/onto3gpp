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
