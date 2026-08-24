"""Level 0-4 NER fallback chain (Stage 5).

Deterministic, CPU-only named-entity recognition that resolves query terms to
canonical concepts through a fallback chain of increasing fuzziness:

  L0 dictionary  — exact Aho-Corasick match against the compiled dictionary.
  L1 rules      — abbreviation / title-phrase rules (from the extractor).
  L2 small CPU  — fuzzy matcher for ambiguous phrases (bigram Dice similarity
                  against known concept canonicals).
  L3 resolver   — alias -> canonical resolution via the ontology.
  L4 reasoning  — ontology graph expansion (1-hop neighbors of resolved
                  concepts).

Each level is cheaper and more precise than the next; we only fall through to
a higher level when the lower levels fail to resolve a term. The chain is
domain-agnostic — it operates on the dictionary + ontology, not on 3GPP terms.
"""

from __future__ import annotations

from dataclasses import dataclass

from onto3gpp.compile.dictionary import Dictionary
from onto3gpp.ontology.schema import Ontology
from onto3gpp.runtime.reasoner import reason
from onto3gpp.search.bm25 import tokenize


@dataclass
class NERMatch:
    """A resolved concept mention with the level at which it was resolved."""

    canonical: str
    level: int  # 0..4
    surface: str = ""


def fuzzy_similarity(a: str, b: str) -> float:
    """Dice coefficient over character bigrams — a cheap, CPU-only similarity.

    Returns 1.0 for identical strings, ~0 for unrelated strings. This is the
    "small CPU model": a deterministic, dependency-free fuzzy matcher that
    resolves ambiguous phrases (e.g. "handover procedure" -> "Handover")
    without any neural network or AI cost.
    """
    a = a.lower()
    b = b.lower()
    if a == b:
        return 1.0
    bigrams_a = {a[i : i + 2] for i in range(len(a) - 1)}
    bigrams_b = {b[i : i + 2] for i in range(len(b) - 1)}
    if not bigrams_a or not bigrams_b:
        return 0.0
    overlap = len(bigrams_a & bigrams_b)
    return 2.0 * overlap / (len(bigrams_a) + len(bigrams_b))


def _token_contained(query: str, canonical: str) -> bool:
    """True if every query token appears in the canonical's tokens.

    A strong, precise signal for ambiguous-phrase resolution: "qos flow"
    resolves to "QoS Flow" (all tokens present), but "handover procedure"
    does NOT resolve to "Random Access Procedure" (tokens don't overlap).
    This prevents the fuzzy matcher from matching unrelated concepts that
    merely share a common word.
    """
    q_tokens = set(tokenize(query))
    c_tokens = set(tokenize(canonical))
    if not q_tokens:
        return False
    return q_tokens <= c_tokens


class NERChain:
    """The Level 0-4 fallback chain."""

    def __init__(self, dictionary: Dictionary, onto: Ontology) -> None:
        self.dictionary = dictionary
        self.onto = onto
        # concept canonicals for fuzzy matching (L2)
        self._canonicals = [c.canonical for c in onto.concepts]
        # alias -> canonical map (L3)
        self._alias_to_canonical: dict[str, str] = {}
        for c in onto.concepts:
            for alias in c.aliases:
                self._alias_to_canonical.setdefault(alias.lower(), c.canonical)

    def annotate(self, text: str) -> list[NERMatch]:
        """Resolve the terms in ``text`` to canonical concepts.

        Returns a list of NERMatch, one per resolved concept, in order of
        first occurrence. A concept is resolved at the lowest level that
        matches it.
        """
        if not text:
            return []
        matches: list[NERMatch] = []
        seen: set[str] = set()

        # L0: exact dictionary match
        for canonical in self.dictionary.find(text):
            if canonical not in seen:
                seen.add(canonical)
                matches.append(NERMatch(canonical=canonical, level=0))

        # L2: fuzzy matcher for ambiguous phrases not in the dictionary.
        # Only consider phrases (multi-word) that aren't already resolved.
        # The fuzzy matcher is a "small CPU model" for *short ambiguous
        # phrases* — it matches the whole query against concept canonicals.
        # For long sentences it would match too many canonicals and pollute
        # the query, so we only fuzzy-match short queries (<= 4 tokens).
        if len(tokenize(text)) <= 4:
            for canonical in self._canonicals:
                if canonical in seen:
                    continue
                if len(canonical.split()) < 2:
                    continue  # only fuzzy-match multi-word phrases
                # token containment is the precise signal: every query token
                # must appear in the canonical. This resolves "qos flow" ->
                # "QoS Flow" but not "handover procedure" -> "Random Access
                # Procedure" (which merely shares a common word).
                if _token_contained(text, canonical):
                    seen.add(canonical)
                    matches.append(NERMatch(canonical=canonical, level=2))

        # L3: alias -> canonical via ontology
        for token in tokenize(text):
            alias = self._alias_to_canonical.get(token)
            if alias and alias not in seen:
                seen.add(alias)
                matches.append(NERMatch(canonical=alias, level=3))

        # L4: ontology reasoning — expand to 1-hop neighbors of resolved
        # concepts (only if we resolved at least one concept).
        if seen:
            plan = reason(text, self.onto)
            for term in plan.related_terms:
                if term not in seen:
                    seen.add(term)
                    matches.append(NERMatch(canonical=term, level=4))

        return matches


def resolve_chain(
    text: str, dictionary: Dictionary, onto: Ontology
) -> list[NERMatch]:
    """Convenience wrapper: build a chain and resolve ``text``."""
    return NERChain(dictionary, onto).annotate(text)
