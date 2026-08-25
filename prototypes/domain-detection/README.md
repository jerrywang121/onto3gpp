# Prototype: Domain Auto-Detection

**Question:** When ingesting a document without an explicit domain, how should
we detect which domain pack to use?

**Options compared:**

1. **Keyword / signature classifier (deterministic, CPU-only).** Score each
   domain pack by how many of its distinctive terms (from the domain's
   `config.yaml` concept/relation types + a small seed term list) appear in the
   document. Pick the highest-scoring pack above a threshold; fall back to
   "unknown" otherwise.
   - Pros: zero AI cost, explainable, fast, no network.
   - Cons: weak for overlapping domains; needs a seed term list per domain.

2. **LLM classifier (AI).** Send a sample of the document (first N chunks) to
   the `domain_detect` model and ask it to return a domain id from the
   registered packs.
   - Pros: handles ambiguous/overlapping domains well; no per-domain seed list.
   - Cons: AI cost per ingestion; non-deterministic; needs the LLM enabled.

3. **Hybrid.** Keyword classifier first; only invoke the LLM when the keyword
   score is below a confidence threshold (i.e. AI fills the gap).

**How to measure:** Build a small labeled set of documents (one per domain,
plus a few ambiguous ones). Report accuracy, latency, and AI cost per document
for each option. The hybrid wins if it matches the LLM's accuracy on ambiguous
docs while costing near-zero on clear ones.

**Status:** Not yet run. Outcome to be recorded in an ADR (see ADR-0011).
