# Prototype: ABox Merge / Conflict Resolution

**Question:** When merging extracted instances into the low-level knowledge
graph (ABox), how should we detect and resolve conflicts (same concept with
different types, contradictory relations, near-duplicate entities)?

**Options compared:**

1. **Deterministic similarity (default).** Use string/embedding-free similarity
   (normalized name, alias overlap, type match) to detect near-duplicates and
   conflicts. Resolve by deterministic rules (e.g. prefer the entry with more
   provenance, or the higher-confidence extraction).
   - Pros: zero AI cost, explainable, deterministic, fast.
   - Cons: brittle for paraphrased or semantically-similar-but-different terms.

2. **LLM-judged merge.** For ambiguous cases only, ask the `merge` model whether
   two candidates are the same concept and how to reconcile conflicting
   relations.
   - Pros: handles semantic ambiguity well.
   - Cons: AI cost; non-deterministic; needs the LLM enabled.

3. **Hybrid.** Deterministic similarity first; route only below-threshold /
   conflicting cases to the LLM judge.

**How to measure:** Build a small set of merge cases (true duplicates, true
distinct, conflicts). Report precision/recall of duplicate detection and the
correctness of conflict resolution, plus AI cost. The hybrid is expected to win
on cost while matching the LLM's accuracy on ambiguous cases.

**Status:** Not yet run. Outcome to be recorded in an ADR (see ADR-0011).
