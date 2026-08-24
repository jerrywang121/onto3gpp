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
