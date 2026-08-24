"""Ontology reasoner → query IR / search plan (Stage 2).

Deterministic, CPU-only reasoning over the ontology graph. Given a query,
resolve the concepts it mentions (via the compiled dictionary) and expand to
a search plan: primary terms (the query concepts) plus related terms (their
1-hop neighbors in the ontology graph). This lets retrieval match on related
concepts even when the query only names one.

The reasoner is domain-agnostic — it operates on the ontology graph, not on
3GPP-specific terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from onto3gpp.ontology.schema import Ontology

# Stopwords that should never be treated as meaningful related terms (they
# appear as noisy concepts in the ontology, e.g. "AND", "OF", "AS").
_STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "by",
    "with", "from", "at", "as", "is", "are", "be", "that", "this", "each",
    "during", "between", "while", "how", "what", "which", "when", "it",
    "its", "not", "no", "so", "if", "then", "than", "into", "over", "under",
    "via", "per", "etc", "e.g", "i.e", "and/or",
}

# Cap on related terms expanded per query concept. Hub concepts (e.g. "UE"
# with degree 457) have far too many 1-hop neighbors to be useful — expanding
# to all of them pollutes the query and makes the reranker boost everything.
# We keep only the most-connected few, which are the most salient neighbors.
_MAX_RELATED_PER_CONCEPT = 8


@dataclass
class SearchPlan:
    """A query IR: primary terms + related terms + explanation trace."""

    primary_terms: list[str] = field(default_factory=list)
    related_terms: list[str] = field(default_factory=list)
    explanation: list[str] = field(default_factory=list)


def _concept_by_canonical(onto: Ontology) -> dict[str, str]:
    """Map lowercase canonical → (concept id, original canonical)."""
    return {c.canonical.lower(): (c.id, c.canonical) for c in onto.concepts}


def _concept_by_alias(onto: Ontology) -> dict[str, str]:
    """Map lowercase alias → (concept id, original canonical).

    Aliases are additional surface forms for a concept (e.g. "HO" for
    "handover"). Resolving them lets the reasoner recognize a concept even
    when the query uses a non-canonical surface form. A canonical that is
    also an alias of another concept is not shadowed here — canonical
    resolution takes precedence in `reason`.
    """
    by_alias: dict[str, str] = {}
    for c in onto.concepts:
        for alias in c.aliases:
            key = alias.lower()
            # don't let an alias shadow a canonical (canonical wins)
            if key not in by_alias:
                by_alias[key] = (c.id, c.canonical)
    return by_alias


def _neighbors(onto: Ontology, concept_id: str) -> list[str]:
    """Return the canonical names of 1-hop neighbors of a concept, ranked by
    the neighbor's own degree (most-connected first) and capped.

    Ranking by degree keeps the most salient neighbors of a hub concept
    (e.g. the top few neighbors of "UE") while dropping the long tail of
    weakly-connected noise.
    """
    # degree of each concept (number of relations it participates in)
    degree: dict[str, int] = {}
    for r in onto.relations:
        degree[r.source] = degree.get(r.source, 0) + 1
        degree[r.target] = degree.get(r.target, 0) + 1

    neighbors: list[str] = []
    seen: set[str] = set()
    for r in onto.relations:
        if r.source == concept_id:
            target = next((c for c in onto.concepts if c.id == r.target), None)
            if target and target.canonical not in seen:
                seen.add(target.canonical)
                neighbors.append(target.canonical)
        elif r.target == concept_id:
            source = next((c for c in onto.concepts if c.id == r.source), None)
            if source and source.canonical not in seen:
                seen.add(source.canonical)
                neighbors.append(source.canonical)

    # rank by degree (descending), then by name for determinism
    neighbors.sort(key=lambda n: (-degree.get(n, 0), n))
    return neighbors[:_MAX_RELATED_PER_CONCEPT]


def reason(query: str, onto: Ontology) -> SearchPlan:
    """Build a search plan from a query by resolving concepts and expanding
    to their 1-hop neighbors in the ontology graph.

    Concept resolution is a simple case-insensitive whole-word match of the
    query against concept canonicals (the compiled dictionary provides the
    full surface-form resolution at runtime; here we use canonicals directly).
    """
    by_canonical = _concept_by_canonical(onto)
    by_alias = _concept_by_alias(onto)
    lower = query.lower()

    primary: list[str] = []
    related: list[str] = []
    explanation: list[str] = []

    # canonical resolution first (canonical wins over alias)
    resolved: dict[str, str] = {}  # concept id -> original canonical
    for canonical, (cid, original) in by_canonical.items():
        # whole-word match so short canonicals don't match inside longer words
        import re

        pattern = r"(?<![a-z0-9])" + re.escape(canonical) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            resolved[cid] = original

    # alias resolution for concepts not already matched by canonical
    for alias, (cid, original) in by_alias.items():
        if cid in resolved:
            continue
        import re

        pattern = r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            resolved[cid] = original

    for cid, original in resolved.items():
        primary.append(original)
        explanation.append(f"query mentions concept: {original}")
        for neighbor in _neighbors(onto, cid):
            # skip stopwords and single-char noise so expansion doesn't
            # pollute the query with meaningless terms
            if neighbor.lower() in _STOPWORDS or len(neighbor) <= 1:
                continue
            if neighbor not in related:
                related.append(neighbor)
        if related:
            explanation.append(
                f"expanded to related concepts: {', '.join(related)}"
            )

    return SearchPlan(
        primary_terms=primary,
        related_terms=related,
        explanation=explanation,
    )
