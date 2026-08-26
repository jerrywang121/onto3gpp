# ADR-0013: Graph Storage Format (TBox + ABox)

- **Status:** Accepted
- **Date:** 2026-08-25
- **Stage:** 7 (Two-level graph)
- **Related:** ADR-0010

## Context

The two-level graph (TBox + ABox, ADR-0010) needs a storage format. The
current ontology is stored as **JSON** (`data/ontology.json`), which is simple
and reuses existing serialization. But as the low-level knowledge graph grows
(concrete objects, relations, metadata, provenance), JSON may not scale or
support rich graph queries. The choice of storage format is an **open
architecture question** that should be resolved by a throwaway prototype before
committing.

## Decision

**For v1, store both the TBox and ABox as JSON** (reusing the existing
`ontology_to_dict` / `ontology_from_dict` serialization). This is the
lowest-friction path and keeps the runtime load path unchanged.

**Prototype the alternatives** in `prototype/graph-storage/` before committing
to a graph backend:

- **JSON (v1 baseline).** Simple, reuses existing serialization, no new
  dependency. Weak for very large graphs and complex graph queries.
- **NetworkX.** In-memory graph model with rich algorithms (BFS, centrality,
  connected components). Adds a dependency and a serialization layer, but
  enables graph algorithms the runtime could use.
- **RDF/Turtle (OWL TBox + RDF ABox).** Standards-based, interoperable,
  supports formal reasoning. Heavier tooling and a steeper learning curve.
- **Graph DB (Neo4j).** Best for very large graphs and Cypher queries, but adds
  an external service dependency.

The prototype will measure: load time, query time, serialization size, and
ease of the TBox/ABox constraint check (ADR-0010) for each option on the real
3GPP data. The outcome is recorded in this ADR (status → Accepted/Rejected) and
the chosen format is adopted.

## Options Considered

- **JSON (chosen for v1).** Lowest friction; reuses existing serialization.
- **NetworkX.** Richer graph algorithms; adds a dependency.
- **RDF/Turtle.** Standards-based; heavier tooling.
- **Graph DB (Neo4j).** Best scale; external service dependency.

## Rationale

- JSON is the pragmatic v1 choice: it reuses the existing serialization, keeps
  the runtime load path unchanged, and is trivially debuggable.
- The storage format is a genuine open question, so it is resolved by a
  throwaway prototype (per AGENTS.md §1.3) rather than by assumption.

## Consequences

- **Positive:** v1 ships with zero new dependencies; the prototype gives
  evidence for a future migration if scale demands.
- **Negative:** JSON may not scale to very large graphs; graph algorithms are
  limited until a richer backend is adopted.
- **Trade-off:** we accept a possible future migration in exchange for a fast,
  dependency-free v1.

## Open Questions

- At what graph size does JSON become a bottleneck?
- Does the runtime need graph algorithms (centrality, subgraph matching) that
  JSON can't provide?

## Prototype Outcome (Stage 7)

The `prototype/graph-storage/` comparison was resolved in favor of **JSON for
v1**:

- **JSON (chosen).** Reuses the existing `ontology_to_dict` /
  `ontology_from_dict` serialization; zero new dependencies; the runtime load
  path is unchanged. The TBox and ABox serialize cleanly to plain dicts
  (`tbox_to_dict` / `abox_to_dict`). Load time and memory are trivial for the
  current 3GPP dataset (5778 concepts / 22719 relations).
- **NetworkX / RDF / graph-DB.** Deferred. The runtime's current traversal
  patterns (1-hop neighbor expansion in the reasoner) are simple and served
  fine by in-memory dicts. A graph backend would add a dependency or external
  service without a measurable benefit at this scale.

**Decision:** JSON remains the storage format for v1. Revisit when the graph
grows or the runtime needs richer graph algorithms (centrality, subgraph
matching).
