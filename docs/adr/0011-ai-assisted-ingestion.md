# ADR-0011: AI-Assisted Knowledge Ingestion (TBox + ABox build/refine)

- **Status:** Accepted
- **Date:** 2026-08-25
- **Stage:** 9 (AI-assisted knowledge ingestion)
- **Related:** ADR-0001, ADR-0004, ADR-0005, ADR-0010, ADR-0012

## Context

Ingestion is where AI does its primary knowledge-engineering work. For each
incoming document, the app must:

1. **Auto-determine the domain** if not specified by the user.
2. **Bootstrap** the top-level domain-specific ontology (TBox) if it doesn't
   yet exist.
3. On input docs/contents:
   - **Extract** domain-specific terms and relations.
   - **Check** against the existing TBox; **align** on concept types, relation
     types, and graph constraints.
   - If needed (new concept type, relation type, or connection discovered),
     **update the TBox** accordingly.
   - **Add** new terms/relations to the low-level knowledge graph (ABox); if
     needed, **merge** similar objects/relations and **resolve conflicts**.

This must be **domain-general** (driven by domain packs), **no
human-in-the-loop** (AI-as-judge gates every decision), and **evidence-based**
(ADR-0005). The runtime query path stays deterministic and AI-free.

## Decision

Adopt a **deterministic-first, AI-fills-the-gaps, judge-gated** ingestion
pipeline in a new `src/onto3gpp/ingest/` module:

```
input doc
   │
   ▼
1. Domain Auto-Detection        (AI if not specified by the user)
   │
   ▼
2. TBox Bootstrap               (create top-level ontology if absent)
   │
   ▼
3. Parse + Structure Extract    (deterministic)
   │
   ▼
4. Extract terms + relations    (rules + AI)
   │
   ▼
5. TBox Alignment               (check against top-level ontology)
   │
   ├─► conforms ────────────────► 6a. ABox Merge (dedupe / conflict-resolve)
   └─► new type/rel/connection ─► 6b. TBox Evolution (gated, auditable)
   │
   ▼
7. AI-as-Judge Gate             (against gold set + provenance)
   │
   ▼
8. Compile → Knowledge Pack      (dictionary, rules, intents, index)
```

**Where AI is used (offline only):**
- **Domain auto-detection** — if the user doesn't specify the domain, classify
  the document's domain (prototype: keyword vs. LLM classifier).
- **TBox bootstrap** — if no TBox exists, create one. **Curated in the domain
  pack by default**; AI may propose extensions (ADR-0010).
- **Term/relation extraction** — rules first, AI for the residual (existing
  `extract/terms.py`, `extract/relations.py` + LLM prompts).
- **TBox alignment** — check extracted entries against the TBox; flag new
  concept types, relation types, or connections.
- **TBox evolution** — if new types/connections are discovered with sufficient
  evidence, update the TBox. Gated and auditable (ADR-0005): a TBox change is
  promoted only if it improves (or doesn't regress) the eval metrics and is
  grounded in provenance.
- **ABox merge / conflict resolution** — add new terms/relations to the
  low-level KG; merge similar objects/relations; resolve conflicts.
  **Deterministic similarity first, AI-judge for ambiguous cases.**

**Where AI is NOT used:**
- The runtime query path (core search) is always deterministic and AI-free.
- Answer synthesis is optional post-processing, not core search.

## Options Considered

- **Fully deterministic ingestion.** Rejected: rules miss semantic duplicates,
  new types, and cross-document relations; AI is needed for the residual.
- **Fully AI-driven ingestion.** Rejected: expensive, less auditable, and
  violates the deterministic-first principle.
- **Deterministic-first, AI-fills-the-gaps (chosen).** Rules handle the common
  case cheaply; AI handles the residual; every AI decision is judge-gated.

## Rationale

- Matches the clarified offline-AI / CPU-runtime split: AI does the
  knowledge-engineering, never the core query path.
- Deterministic-first keeps cost low and output auditable; AI fills only the
  gaps rules can't handle.
- Judge-gating (ADR-0001) + evidence-based evolution (ADR-0005) preserve the
  no-human-in-the-loop principle.
- Domain-general: every step is driven by the domain pack (prompts + config).

## Consequences

- **Positive:** a coherent, auditable, domain-general ingestion path that
  builds and refines both the TBox and the ABox without human review.
- **Negative:** more moving parts (detect, bootstrap, extract, align, evolve,
  merge); TBox evolution must be conservative to avoid schema drift.
- **Trade-off:** we accept slower, safer TBox evolution over aggressive
  refactors (consistent with ADR-0005).

## Open Questions

- What evidence threshold justifies a TBox evolution (new type/relation)?
- How to measure merge precision (share of merged objects that are true
  duplicates) for the ingestion eval gate?
