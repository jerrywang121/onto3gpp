# ADR-0005: Ontology Evolution Strategy (evidence-based)

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 4 (AI-as-Judge Improvement Loop)

## Context

The ontology must **evolve iteratively** without human-in-the-loop. We need an
evidence-based strategy for how the AI-as-judge improvement loop should modify
the ontology (add/remove concepts, aliases, relations) so that metrics improve
reliably and the ontology stays coherent.

## Evidence (literature review, 2026-08-24)

Three recent works directly inform the strategy:

1. **KG-SEA** (Silesian Univ. of Tech., 2026) — "Self-Evolving Framework for
   Iterative KG Construction". Reframes KG construction as iterative
   optimization with two modules: an **Ontology Analyst** (identifies
   redundancies + knowledge gaps) and an **Ontology Curator** (executes
   *validated* graph transformations). Reports node counts reduced 4-5%,
   relation types consolidated 7-8%, organizational scores 63-66% → 67-68%.
   **Conclusion: iterative refinement is essential** for robust KGs.

2. **EvoRAG** (arXiv 2604.15676, 2026) — "Feedback-driven Backpropagation".
   Uses a **relation-centric evolution** strategy: entities are shared across
   many triplets, so modifying them causes *cascading and ambiguous effects*;
   each relation uniquely defines a triplet's semantic intent. Low-quality
   triplets are **softly suppressed** (deprioritized in retrieval) rather than
   hard-deleted, so they can regain contribution if they prove useful again.
   Gating uses mean/std thresholds over contribution scores. Improves
   reasoning accuracy 7.34% over SOTA KG-RAG.

3. **Ontology Learning comparison** (arXiv 2511.05991, 2025) — Ontology-guided
   KGs **with chunk information** match GraphRAG (90% accuracy); without chunk
   info they collapse (15-20%). **Chunk integration into graph nodes is
   critical for factual grounding.** Also: ontology from a static relational
   schema needs one-time learning (cheaper) vs. text-derived (needs merging).

## Decision

Adopt a **relation-centric, feedback-gated, chunk-grounded** evolution
strategy:

1. **Prefer relation/alias additions over entity edits.** When the improvement
   loop proposes changes, favor adding relations and aliases (which are
   localized) over renaming/merging concepts (which cascade). This matches
   EvoRAG's finding and our `apply_proposals` review rules.
2. **Gate every proposal against the eval set.** A proposal is promoted only
   if the hold-out eval metrics improve (or don't regress). This is the
   AI-as-judge gate (ADR-0001) applied to evolution.
3. **Soft suppression over hard deletion.** When a relation is low-quality,
   deprioritize it (lower weight) rather than delete it, so it can recover if
   it later proves useful. Our `Relation.weight` field supports this.
4. **Keep chunk grounding.** Every concept/relation carries provenance
   (spec + clause) so the ontology stays grounded in retrievable text chunks.
   This is already the case (schema.py `provenance`); preserve it in all
   evolution steps.
5. **Consolidate redundancies.** The improvement loop should detect duplicate
   concepts/aliases and consolidate them (KG-SEA's Analyst/Curator split).

## Consequences

- **Positive:** evolution is localized (low blast radius), evidence-gated
  (no regressions), and grounded (chunk provenance preserved). Aligns with
  the no-human-in-the-loop principle.
- **Negative:** relation-centric evolution may miss entity-level refactors that
  would help; soft suppression keeps some noise in the graph.
- **Trade-off:** we accept slower, safer evolution over aggressive refactors.

## Alternatives Considered

- **Entity-centric evolution** (rename/merge concepts) — rejected: cascading
  effects on shared entities (EvoRAG evidence).
- **Hard deletion of low-quality relations** — rejected: loses recoverability;
  soft suppression is safer.
- **No evolution / static ontology** — rejected: KG-SEA shows iterative
  refinement is essential for robust RAG.

## Open Questions

- What is the minimum hold-out eval set size for reliable promotion gating?
- Should relation weights be learned from feedback (EvoRAG-style contribution
  scores) or set by the judge's confidence?
