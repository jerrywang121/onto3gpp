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


def _adjacency(onto: Ontology) -> dict[str, list[str]]:
    """Map concept id -> list of neighbor concept ids (undirected)."""
    adj: dict[str, list[str]] = {}
    for r in onto.relations:
        adj.setdefault(r.source, []).append(r.target)
        adj.setdefault(r.target, []).append(r.source)
    return adj


def _neighbors_up_to(
    onto: Ontology, start_id: str, max_hops: int
) -> list[str]:
    """Return the canonical names of concepts reachable from ``start_id`` in
    1..max_hops hops (BFS), ranked by the neighbor's own degree (most-connected
    first) and capped per hop.

    Multi-hop reasoning lets a query reach second-degree (and beyond) related
    concepts. Each hop's frontier is capped so hub concepts don't explode the
    expansion.
    """
    if max_hops <= 0:
        return []

    adj = _adjacency(onto)
    id_to_canonical = {c.id: c.canonical for c in onto.concepts}
    degree: dict[str, int] = {}
    for r in onto.relations:
        degree[r.source] = degree.get(r.source, 0) + 1
        degree[r.target] = degree.get(r.target, 0) + 1

    # BFS from start_id, tracking hop distance
    visited: set[str] = {start_id}
    frontier: list[str] = [start_id]
    distance: dict[str, int] = {start_id: 0}
    collected: list[str] = []

    for hop in range(1, max_hops + 1):
        next_frontier: list[str] = []
        hop_neighbors: list[str] = []
        for node in frontier:
            for nb in adj.get(node, []):
                if nb in visited:
                    continue
                visited.add(nb)
                distance[nb] = hop
                next_frontier.append(nb)
                canonical = id_to_canonical.get(nb)
                if canonical:
                    hop_neighbors.append(canonical)
        # rank this hop's neighbors by degree (descending), then name
        hop_neighbors.sort(key=lambda n: (-degree.get(n, 0), n))
        collected.extend(hop_neighbors[:_MAX_RELATED_PER_CONCEPT])
        frontier = next_frontier
        if not frontier:
            break

    return collected


def reason(query: str, onto: Ontology, max_hops: int = 1) -> SearchPlan:
    """Build a search plan from a query by resolving concepts and expanding
    to their neighbors in the ontology graph.

    ``max_hops`` controls the reasoning depth: 1 (default) expands to 1-hop
    neighbors, 2 to 2-hop neighbors, etc. 0 disables expansion entirely.

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
        for neighbor in _neighbors_up_to(onto, cid, max_hops):
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
