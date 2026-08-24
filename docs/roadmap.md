# onto3gpp — Staged Roadmap

> **Status:** Living document. Update as stages complete.
> **Last updated:** 2026-08-24

This is the staged feature plan. Each stage is a vertical slice that ends with
a measurable evaluation (see `docs/status.md` for live metrics). A stage is
"done" only when its **stage gate** passes (see `AGENTS.md` §1.2).

---

## Stage 0 — Baseline (parse + index + BM25)

**Goal:** Establish a measurable baseline before any ontology work.

**Tasks:**
- [x] Domain-pack skeleton (`docs/domain/_template` + `docs/domain/3gpp`).
- [x] Document parser: `.docx`/`.pdf`/`.text` → structured sections (clause
      hierarchy).
- [x] Chunker with section metadata (spec, release, clause, title).
- [x] BM25 index + search.
- [x] Gold set bootstrap (`data/gold_queries.jsonl`, ~100–300 real queries).
- [x] Eval harness: MRR, NDCG@k, Recall@k.

**Stage gate:** Baseline metrics recorded in `docs/status.md`. Eval harness
runs end-to-end.

**Branch:** `stage/0-baseline`

---

## Stage 1 — Terminology (extract + compile dictionary)

**Goal:** Measure the lift from a compiled terminology dictionary.

**Tasks:**
- [x] Candidate term extraction (rules first, optional LLM).
- [x] AI-as-judge gate for candidate terms (against gold set + provenance).
- [x] Ontology compiler → Aho-Corasick trie + dictionary.
- [x] Runtime NER (dictionary path).
- [x] Query expansion → BM25.
- [ ] Measure term-expansion lift on **real** 3GPP documents (blocked on data).

**Stage gate:** Term-expansion lift measured vs. Stage 0 baseline.

> **Status:** mechanism implemented and unit-tested. Lift not yet measurable
> on the synthetic sample (plain BM25 already perfect). Gate pending real docs.

**Branch:** `stage/1-terminology`

---

## Stage 2 — Ontology + Relations

**Goal:** Relationship-aware ranking.

**Tasks:**
- [ ] Concept/relation schema + merge + validate + version.
- [ ] Relation extraction (rules + LLM) with AI-as-judge gate.
- [ ] Ontology reasoner → query IR.
- [ ] Relationship-aware reranker.

**Stage gate:** Relationship-aware ranking lift vs. Stage 1.

**Branch:** `stage/2-ontology`

---

## Stage 3 — Intent + Structure Boosts

**Goal:** Intent-aware results.

**Tasks:**
- [ ] Intent detector (pattern-based, from domain pack).
- [ ] Structure-aware boosts (spec/clause relevance).
- [ ] Reranker integration.

**Stage gate:** Intent-aware results lift vs. Stage 2.

**Branch:** `stage/3-intent`

---

## Stage 4 — AI-as-Judge Improvement Loop

**Goal:** Closed-loop recursive improvement with no human-in-the-loop.

**Tasks:**
- [ ] Search-log collection.
- [ ] Offline analysis (missed terms, mismatches, co-occurrences).
- [ ] LLM proposal generation.
- [ ] AI-as-judge scoring against hold-out eval set.
- [ ] Auto-promote / auto-reject with regression logging.

**Stage gate:** Closed-loop improvement demonstrated; metrics improve over
multiple iterations without human review.

**Branch:** `stage/4-improve-loop`

---

## Stage 5 — Optional Small CPU NER Model

**Goal:** Handle residual ambiguity.

**Tasks:**
- [ ] Level 0–4 fallback chain (dictionary → rules → small model → resolver →
      reasoning).
- [ ] Small CPU NER model for ambiguous phrases only.

**Stage gate:** Residual-ambiguity improvement measured; CPU cost documented.

**Branch:** `stage/5-cpu-ner`

---

## Cross-Cutting Work

- **Domain generality:** every stage must keep the pipeline domain-agnostic
  (driven by domain packs). Re-validate at each stage gate.
- **ADR maintenance:** update `docs/adr/` for every decision.
- **Status tracking:** update `docs/status.md` after every stage.

---

## Roll-back / Alternative Trials

If a stage's metrics don't meet the gate, or a better alternative emerges:

1. Create a `trial/<name>` branch.
2. Prototype/implement the alternative there.
3. Compare metrics.
4. Roll back or promote based on evidence.
5. Record in an ADR.

See `AGENTS.md` §3.
