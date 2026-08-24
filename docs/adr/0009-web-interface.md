# ADR-0009: Web Interface for Runtime Exploration

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 6 (Web Explorer)

## Context

The runtime query path is deterministic and CPU-only, but currently only
exposed through the CLI (`query` command) and the eval harness. To let users
explore the system interactively — and to make the ontology's structure
visible — we need a lightweight web interface. It must:

- Let a user type a query and see **ranked candidate results**.
- Expose the runtime's **query parameters** (top-k, reasoning hop count,
  fuzzy threshold, and which pipeline stages are enabled).
- Show the **extracted concepts/terms/objects**, filterable by text.
- Show a **topology graph** of the ontology (concepts + relations).

The interface is a **human exploration tool**, not part of the deterministic
runtime contract. It must stay dependency-light and require no build step.

## Decision

Add a **FastAPI + vanilla-JS web app** under `src/onto3gpp/web/`, served by a
new `serve` CLI command:

- **Backend** (`app.py`): a `create_app(parsed_dir, dict_path, ontology_path)`
  factory that loads chunks, the compiled dictionary, and the ontology into a
  `Runtime` object, then exposes:
  - `POST /api/query` — ranked results. Params: `query`, `top_k`, `max_hops`,
    `fuzzy_threshold`, and booleans `use_chain`, `use_ontology`,
    `use_structure`. Returns the search plan (primary/related terms +
    explanation) plus ranked chunks.
  - `GET /api/concepts` — list of extracted concepts, filterable by `q`
    (text) and `type`, with `limit`.
  - `GET /api/graph` — ontology neighborhood around a `concept` within
    `radius` hops, capped by `limit`.
  - `GET /api/meta` — counts (chunks, specs, concepts, relations, dictionary
    entries).
  - `GET /` + `/static/*` — the single-page frontend.
- **Frontend** (`static/`): three tabs — **Query**, **Concepts**, **Graph**.
  Vanilla JS/HTML/CSS, no build step. The Graph tab renders a self-contained
  force-directed layout on a `<canvas>` (repulsion/attraction/center forces,
  ~300 iterations), with the center concept highlighted.
- **CLI**: `onto3gpp serve --parsed <dir> --dict <path> --ontology <path>
  [--host] [--port]` runs uvicorn with the app.

The web app reuses the existing runtime modules (`reason`, `NERChain`,
`BM25Index`, ontology schema) — it adds no new query logic, only a thin HTTP
and UI layer.

## Alternatives considered

1. **Jupyter notebook / ipywidgets explorer.** Rejected: not a persistent,
   shareable interface; heavier to run; harder to show a live graph.
2. **A React/Next.js frontend with a build step.** Rejected: violates the
   no-build-step, dependency-light goal. Vanilla JS is sufficient for three
   tabs and a canvas graph.
3. **Expose only the CLI.** Rejected: no interactive exploration, no visual
   ontology topology, no parameter experimentation.

## Consequences

- Users can explore the runtime interactively and tune `max_hops`,
  `fuzzy_threshold`, and `top_k` live, seeing the effect on the search plan
  and ranking.
- The ontology's structure is visible as a graph, aiding debugging and
  domain-pack review.
- The web layer is thin and stateless — it does not change the deterministic
  runtime, so the eval metrics are unaffected.
- FastAPI + uvicorn are added as runtime dependencies (they are only used by
  the `serve` command).
