"""Web interface for exploring the onto3gpp runtime (query + ontology browser).

A thin, stateless FastAPI layer over the deterministic runtime. Loads the
compiled dictionary, ontology, and parsed chunks once at startup, builds the
BM25 index, and exposes read-only endpoints for querying, browsing concepts,
and inspecting the ontology topology graph.
"""
