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
        self, query: str, onto, top_k: int = 10, max_hops: int = 1
    ) -> list[SearchResult]:
        """Search with ontology-aware candidate generation.

        The query is scored with plain BM25 (so the query's own signal is not
        polluted by expansion terms). Chunks that mention a related concept
        (a 1-hop neighbor of a query concept) are added to the candidate set
        with a floor score, so the relationship-aware reranker can boost them
        into the top-k even when they share no exact tokens with the query.
        """
        from onto3gpp.runtime.reasoner import reason

        plan = reason(query, onto, max_hops=max_hops)
        # score with the query's own tokens PLUS the resolved primary terms
        # (canonicals of concepts the query mentions, including via aliases).
        # This lets a query that uses an alias ("HO") match chunks that only
        # contain the canonical ("handover").
        q_tokens = tokenize(query)
        for term in plan.primary_terms:
            q_tokens.extend(tokenize(term))
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

    def search_structure(
        self,
        query: str,
        onto,
        dictionary=None,
        top_k: int = 10,
        max_hops: int = 1,
        fuzzy_threshold: float = 0.0,
    ) -> list[SearchResult]:
        """Search with ontology + structure-aware candidate generation.

        Like :meth:`search_ontology`, but additionally adds chunks whose
        clause title or ancestor titles share a token with the query to the
        candidate set (with a floor score). This surfaces clauses whose
        *title* matches the query even when their body text doesn't, so the
        structure-aware reranker can boost them into the top-k.

        If ``dictionary`` is provided, the query is additionally expanded with
        the Level 0-4 NER fallback chain (dictionary exact → fuzzy matcher →
        alias resolver → ontology reasoning), so ambiguous surface forms and
        related concepts contribute to the query tokens.

        ``max_hops`` controls the ontology reasoning depth (1 = 1-hop
        neighbors, 2 = 2-hop, etc.). ``fuzzy_threshold`` sets the minimum Dice
        similarity for the L2 fuzzy matcher to accept an ambiguous-phrase
        match.
        """
        from onto3gpp.runtime.reasoner import reason
        from onto3gpp.runtime.structure import build_ancestor_map

        plan = reason(query, onto, max_hops=max_hops)
        q_tokens = tokenize(query)
        for term in plan.primary_terms:
            q_tokens.extend(tokenize(term))
        if dictionary is not None:
            from onto3gpp.runtime.ner_chain import NERChain

            # Only add L2 (fuzzy) and L3 (alias) resolutions to the query
            # tokens. L0 (dictionary exact) and L4 (ontology reasoning) are
            # already handled by `reason()` above — adding them again would
            # pollute the query with hub-related terms and regress ranking.
            chain = NERChain(dictionary, onto, fuzzy_threshold=fuzzy_threshold)
            for m in chain.annotate(query):
                if m.level in (2, 3):
                    q_tokens.extend(tokenize(m.canonical))
        if not q_tokens:
            return []
        scores = self.bm25.get_scores(q_tokens)
        related = set(plan.related_terms)

        # structure: map clause -> ancestor clauses, and clause -> chunk
        amap = build_ancestor_map(self.chunks)
        chunks_by_clause: dict[str, Chunk] = {}
        for c in self.chunks:
            if c.clause not in chunks_by_clause:
                chunks_by_clause[c.clause] = c
        q_set = set(q_tokens)

        # A title match is a strong relevance signal: a clause titled
        # "Handover" for a handover query should rank near the top even if its
        # body text doesn't contain the query tokens. Add a structure boost
        # proportional to how many query tokens the title+ancestor titles
        # share, scaled to the best BM25 score. This lets specific matches
        # (many shared tokens) rank above generic ones (a single shared token
        # like "RRC"), and lets a clause with a partial BM25 score (e.g. 18.1
        # for an SDT query) rise above unrelated high-scoring chunks.
        max_score = max(scores) if len(scores) else 0.0

        # precompute title-token overlap per clause
        title_overlap: dict[str, int] = {}
        for c in self.chunks:
            if c.clause in title_overlap:
                continue
            tt: set[str] = set()
            for clause in [c.clause] + amap.get(c.clause, []):
                t = chunks_by_clause.get(clause)
                if t is not None:
                    tt.update(tokenize(t.title))
            title_overlap[c.clause] = len(q_set & tt)
        max_overlap = max(title_overlap.values()) if title_overlap else 0

        candidates: list[SearchResult] = []
        for i, chunk in enumerate(self.chunks):
            s = scores[i]
            # structure boost: proportional to title-token overlap
            ov = title_overlap.get(chunk.clause, 0)
            frac = ov / max_overlap if max_overlap else 0.0
            structure_boost = max_score * frac * 0.4
            combined = s + structure_boost
            if combined > 0:
                candidates.append(SearchResult(chunk=chunk, score=combined))
                continue
            # no lexical or structure match; keep as a candidate only if it
            # mentions a related concept (floor score so the reranker can boost)
            text_lower = chunk.text.lower()
            if any(t.lower() in text_lower for t in related):
                candidates.append(SearchResult(chunk=chunk, score=1e-6))

        candidates.sort(key=lambda r: r.score, reverse=True)
        return candidates[:top_k]
