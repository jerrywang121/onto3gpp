# Prototype: Graph Storage

**Question:** How should the two-level graph (TBox + ABox) be stored and
queried at runtime?

**Options compared:**

1. **JSON files (v1 default).** The TBox and ABox are plain JSON documents
   (as `data/ontology.json` is today). The runtime loads them into memory and
   traverses them directly.
   - Pros: zero dependencies, human-readable, diffable, trivially versioned.
   - Cons: no native graph queries; must re-implement traversal; memory-bound
     for very large graphs.

2. **NetworkX.** In-memory graph library. Native traversal, subgraph queries,
   path algorithms.
   - Pros: rich graph algorithms, easy to prototype.
   - Cons: in-memory only; serialization needed for persistence; not a
     database.

3. **RDF / OWL (rdflib).** Standard semantic-web model; aligns with the
   TBox/ABox framing; SPARQL queries.
   - Pros: standards-based, interoperable, SPARQL.
   - Cons: heavier dependency; SPARQL learning curve; overkill for v1.

4. **Graph database (e.g. Neo4j / Memgraph).** Server-backed, scalable,
   Cypher queries.
   - Pros: scales to huge graphs, rich query language.
   - Cons: external service dependency; operational overhead; violates the
     "cheap, CPU-only, zero-AI" runtime goal for small deployments.

**How to measure:** For the current 3GPP dataset (5778 concepts, 22719
relations), compare load time, memory, query latency for the runtime's actual
traversal patterns, and dependency footprint. JSON is expected to win for v1;
revisit when the graph grows.

**Status:** Not yet run. Outcome to be recorded in an ADR (see ADR-0013).
