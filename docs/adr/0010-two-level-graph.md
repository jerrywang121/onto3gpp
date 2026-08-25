# ADR-0010: Two-Level Graph Architecture (TBox + ABox)

- **Status:** Accepted
- **Date:** 2026-08-25
- **Stage:** 7 (Two-level graph)
- **Related:** ADR-0002, ADR-0005, ADR-0011, ADR-0013

## Context

The app must maintain, for each domain, **two levels of graph**:

1. **Top-level ontology graph (TBox / schema):** concept *types* as nodes,
   relation *types* as edges connecting concept types. This is the
   **blueprint / constraint** for extraction and construction of the low-level
   knowledge graph.
2. **Low-level knowledge graph (ABox / instances):** concrete concept
   *objects*, typed relations, metadata, and references to the original
   documents.

Today the ontology is a **single flat level**: `concepts` (each with a `type`)
+ typed `relations`. The `concept_types` / `relation_types` in the domain pack
are flat lists — they are **not a graph**, so there is no constraint linking
"a `network_function` may `use` a `network_function`". This means extraction
can produce relations that violate the domain's intended structure, and there
is no schema to guide or validate the low-level KG.

Both graphs must be **domain-specific** — they cover the domain's concepts and
relations, not general terms.

## Decision

Adopt the standard **TBox / ABox** split:

- **TBox** (`src/onto3gpp/ontology/tbox.py`): `concept_types` (nodes) +
  `relation_type_constraints` (edges: `(source_type, rel, target_type)`). This
  is the blueprint. Curated in the domain pack by default; evolved by AI only
  when evidence demands (ADR-0011).
- **ABox** (`src/onto3gpp/ontology/abox.py`): the existing `Concept` /
  `Relation` model, extended with richer metadata + provenance. This is what
  the runtime already consumes.
- **Constraint checker** (`src/onto3gpp/ontology/align.py`): validates that
  extracted ABox entries conform to the TBox (concept type is known; relation
  type is allowed between those two concept types).
- **Storage:** JSON for v1 (reuses existing serialization); NetworkX / RDF /
  graph-DB are prototype alternatives (ADR-0013).

The TBox answers: *"is a `network_function` allowed to `select` a
`procedure`?"* The ABox answers: *"does `SMF` select `UPF`?"*

## Options Considered

- **Single flat ontology (status quo).** Rejected: no schema/constraint layer;
  extraction can produce structurally invalid relations; no blueprint to guide
  the low-level KG.
- **TBox + ABox (chosen).** The standard ontology framing; clean separation of
  schema (constraint) from instances (data); matches the user's two-level
  requirement directly.
- **RDF/OWL from the start.** Standards-based, but heavier tooling and a
  steeper learning curve; deferred to the storage prototype (ADR-0013).

## Rationale

- The two-level split directly matches the requirement: a top-level ontology
  graph that serves as blueprint/constraint, and a low-level knowledge graph
  of concrete objects with provenance.
- It is the standard, well-understood ontology architecture (TBox/ABox), so it
  is domain-general and extensible.
- It reuses the existing ABox model (the runtime already consumes
  `Concept`/`Relation`), minimizing disruption.
- The TBox-as-constraint gives the AI-assisted ingestion a concrete target to
  align against and evolve (ADR-0011).

## Consequences

- **Positive:** schema/constraint layer guides and validates extraction; the
  low-level KG stays structurally coherent; domain-specific by construction.
- **Negative:** two artifacts to maintain and version; the TBox must be kept in
  sync with the ABox (the align step enforces this).
- **Trade-off:** JSON storage is simple but may not scale to very large graphs;
  the storage prototype (ADR-0013) will decide if/when to move to a graph
  backend.

## Open Questions

- How much TBox structure (subtyping, cardinality constraints) is needed for
  v1 vs. deferred?
- Should the TBox be versioned independently of the ABox, or as one pack?
