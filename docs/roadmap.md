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
- [x] Measure term-expansion lift on **real** 3GPP documents.

**Stage gate:** Term-expansion lift measured vs. Stage 0 baseline.

> **Status:** mechanism implemented and unit-tested. Real 3GPP spec (TS
> 38.300) parsed → 911-term dictionary. On the real gold set
> (`data/gold_queries_38300.jsonl`), term-expansion now **beats plain BM25**
> (MRR 0.667 vs 0.625) after fixing a word-boundary bug in `Dictionary.find`
> (short abbreviations were matching inside longer words). **Gate PASSED.**

**Branch:** `stage/1-terminology`

---

## Stage 2 — Ontology + Relations

**Goal:** Relationship-aware ranking.

**Tasks:**
- [x] Concept/relation schema + merge + validate + version.
- [x] Relation extraction (rules + LLM) with AI-as-judge gate.
- [x] Ontology reasoner → query IR.
- [x] Relationship-aware reranker.

**Stage gate:** Relationship-aware ranking lift vs. Stage 1.

> **Status:** schema + relation extraction done. Built a 879-concept /
> 2027-relation ontology from real TS 38.300. Reasoner + reranker
> implemented. On the real gold set, ontology-aware ranking gives a modest
> MRR lift (0.628 vs 0.625) and a clear Recall@5 lift (0.833 vs 0.750) over
> plain BM25. **Gate partially met** (Recall@5 lift confirmed; MRR marginal).
>
> **Spec coverage expanded:** added TS 38.331 (RRC, V19.3.0) and TS 24.501
> (NAS, V19.7.0) as knowledge sources. The parser was hardened to reject
> NAS table-row clauses (bit-field/IE enumeration rows like "1 UAS services
> enabled") via TOC-title matching (commit `4d74f69`). 124501 now parses to
> 1181 clean sections (was 2107 with ~926 spurious rows). Dictionary rebuilt
> to 5825 entries across all specs.
>
> **Ontology rebuilt over all 4 specs** (commit `f578ed2`): 5788 concepts /
> 26885 relations. Relation extraction optimized with an Aho-Corasick
> automaton (build time 43min → 1.8s). On the 38.300 corpus, ontology-aware
> ranking now gives a **strong lift**: MRR 0.786 (vs 0.669 plain BM25),
> NDCG 0.816, Recall@10 0.917. **Gate MET.**

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
- [x] LLM client abstraction (external AI hooks, LiteLLM-backed) + domain-pack
      `llm:` config.
- [x] LLM judge path (`llm_judge_candidate`) with deterministic fallback.
- [x] Improvement loop scaffold: `propose_improvements` + `apply_proposals`
      (log analysis → LLM proposals → referential-integrity review).
- [ ] Search-log collection.
- [ ] Offline analysis (missed terms, mismatches, co-occurrences).
- [ ] CLI wiring (`onto3gpp improve`, `--llm` flags).
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
