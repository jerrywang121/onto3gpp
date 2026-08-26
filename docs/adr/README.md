# Architecture Decision Records (ADR)

Each ADR records a significant architecture decision, including the options
considered, the decision, and the rationale. This enables roll-back and
alternative trialing.

## Format

Each ADR is a numbered markdown file:

```
docs/adr/0000-template.md
docs/adr/0001-<slug>.md
docs/adr/0002-<slug>.md
```

## Index

- **ADR-0001** — AI-as-judge replaces human-in-the-loop.
- **ADR-0002** — Domain-general pipeline via domain packs.
- **ADR-0003** — Compiled terminology dictionary (Aho-Corasick) for runtime NER.
- **ADR-0004** — Configurable external AI hooks (LiteLLM-backed).
- **ADR-0005** — Ontology evolution strategy (evidence-based).
- **ADR-0006** — Structure-aware boosts.
- **ADR-0007** — Hold-out auto-judge for the improvement loop.
- **ADR-0008** — Level 0-4 NER fallback chain (small CPU model).
- **ADR-0009** — Web interface for runtime exploration.
- **ADR-0010** — Two-level graph architecture (TBox + ABox).
- **ADR-0011** — AI-assisted knowledge ingestion (TBox + ABox build/refine).
- **ADR-0012** — AI provider / model configuration surface (multi-model routing).
- **ADR-0013** — Graph storage format (TBox + ABox).

## Template

```markdown
# ADR-0000: <Title>

- **Status:** Proposed | Accepted | Superseded | Rejected
- **Date:** YYYY-MM-DD
- **Related:** ADR-XXXX

## Context
What is the problem/decision? What are the constraints?

## Decision
What did we decide?

## Options Considered
- Option A: ...
- Option B: ...

## Rationale
Why this option? What evidence/metrics support it?

## Consequences
What are the trade-offs, follow-ups, and roll-back path?
```

## Index

| ADR | Title | Status |
|-----|-------|--------|
| 0001 | AI-as-judge replaces human-in-the-loop | Accepted |
| 0002 | Domain-general pipeline via domain packs | Accepted |
| 0003 | Compiled terminology dictionary (Aho-Corasick) for runtime NER | Accepted |
| 0004 | Configurable external AI hooks (LiteLLM-backed) | Accepted |
| 0005 | Ontology evolution strategy (evidence-based) | Accepted |
| 0006 | Structure-aware boosts | Accepted |
| 0007 | Hold-out auto-judge for the improvement loop | Accepted |
| 0008 | Level 0-4 NER fallback chain (small CPU model) | Accepted |
| 0009 | Web interface for runtime exploration | Accepted |
| 0010 | Two-level graph architecture (TBox + ABox) | Accepted |
| 0011 | AI-assisted knowledge ingestion (TBox + ABox build/refine) | Accepted |
| 0012 | AI provider / model configuration surface (multi-model routing) | Accepted |
| 0013 | Graph storage format (TBox + ABox) | Accepted |
