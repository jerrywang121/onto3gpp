# ADR-0002: Domain-General Pipeline via Domain Packs

- **Status:** Accepted
- **Date:** 2026-08-24
- **Related:** ADR-0001

## Context

The project targets 3GPP but must be **general** and easy to adapt to other
domains. The original brainstorm hard-codes 3GPP concepts (AMF, SMF, PDU
Session, TS 23.501, etc.) throughout the design. We need the pipeline to be
domain-agnostic.

## Decision

Drive every AI prompt and pipeline stage from a **domain pack**:

```
docs/domain/
├── _template/          # template for new domains
│   ├── prompts/        # AI prompt templates (parameterized)
│   └── config.yaml     # domain config (concept types, relations, intents)
└── 3gpp/               # the first concrete domain
    ├── prompts/
    └── config.yaml
```

The pipeline code reads the domain pack and never hard-codes domain terms. To
adapt to a new domain, create a new domain pack (copy `_template`, fill in
prompts + config) — no code changes.

## Options Considered

- **Option A — Hard-coded 3GPP (original):** fastest for 3GPP, but not
  reusable.
- **Option B — Domain packs (chosen):** general, configurable, slightly more
  upfront abstraction.
- **Option C — Plugin architecture:** most flexible, but over-engineered for
  now.

## Rationale

The user explicitly requires generality and easy adaptation. Domain packs give
us that with minimal abstraction cost. The data model is already
domain-agnostic (concept types, relation types, intents come from the pack).

## Consequences

- **Open questions to resolve (prototype/ADR):**
  - How much of the pipeline is truly domain-agnostic vs. domain-specific?
  - What is the minimal domain-pack schema?
- **Roll-back path:** if the abstraction proves premature, we can inline the
  3GPP pack and defer generalization. The pack boundary keeps this cheap.
