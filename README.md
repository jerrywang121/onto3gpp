# onto3gpp

A **domain-general pipeline** for constructing an **ontology-guided RAG** system
with an AI assistant, usable **without AI** (or with cheap AI) at runtime to
minimize cost.

> **Core principle:** AI works **offline** as a knowledge engineer and **judge**;
> the runtime is deterministic, explainable, and CPU-only. No human-in-the-loop
> in the build/improve cycle — AI judges its own output against ground truth.

## Why

3GPP (and similar technical domains) have highly structured, repetitive
terminology, while user queries are often vague, abbreviated, or at the wrong
level of abstraction. An ontology bridges that gap — but building and
maintaining it by hand doesn't scale. This project uses AI offline to build and
maintain the ontology, and deterministic methods at runtime to turn queries
into search plans.

## Key Design Decisions

- **AI offline, deterministic runtime.** LLMs only run in the offline
  build/improve/evaluate stages. The runtime query path is explainable and
  runs with zero AI cost.
- **AI-as-judge, no human-in-the-loop.** The bootstrap and iterative
  improvement loops are gated by AI judging its own output against a
  ground-truth gold set (MRR, NDCG, Recall@k). Humans set policy and
  thresholds, not per-candidate review. See `docs/adr/0001-ai-as-judge.md`.
- **Domain-general.** 3GPP is the first domain, but every AI prompt, schema,
  and pipeline stage is driven by a **domain pack** (prompts + config), never
  hard-coded to 3GPP. See `docs/adr/0002-domain-general.md`.

## Documentation

| Doc | Purpose |
|-----|---------|
| [`AGENTS.md`](AGENTS.md) | Development process rules (staged, evaluated, roll-back-able) |
| [`docs/architecture.md`](docs/architecture.md) | High-level architecture (living doc) |
| [`docs/roadmap.md`](docs/roadmap.md) | Staged feature plan + stage gates |
| [`docs/status.md`](docs/status.md) | Live status tracker (metrics per stage) |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |
| [`docs/domain/`](docs/domain/) | Domain packs (prompts + config) |

## Development

```bash
# Install (editable)
pip install -e ".[dev]"

# Run tests
pytest

# CLI
onto3gpp version
```

## Roadmap (summary)

| Stage | Focus |
|-------|-------|
| 0 | Baseline: parse + index + BM25 |
| 1 | Terminology: extract + compile dictionary |
| 2 | Ontology + relations |
| 3 | Intent + structure boosts |
| 4 | AI-as-judge improvement loop |
| 5 | Optional small CPU NER model |

See [`docs/roadmap.md`](docs/roadmap.md) for details.
