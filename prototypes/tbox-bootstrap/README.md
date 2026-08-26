# Prototype: TBox Bootstrap

**Question:** When a domain has no top-level ontology (TBox) yet, how should we
create the initial concept types, relation types, and relation-type
constraints?

**Options compared:**

1. **Curated (default).** The domain pack ships a hand-written TBox in
   `config.yaml` (as 3GPP does). Ingestion uses it as-is; no AI involved.
   - Pros: high quality, explainable, deterministic, zero AI cost.
   - Cons: requires a human to author the initial TBox per domain.

2. **AI-generated.** Ask the LLM to propose a TBox from a sample of the
   documents (concept types, relation types, and constraints). Human/AI-judge
   reviews before promotion.
   - Pros: fast bootstrap for new domains with no authored TBox.
   - Cons: AI cost; quality varies; needs review; non-deterministic.

3. **Hybrid.** Start from a minimal generic TBox (a few universal types like
   `concept`, `procedure`, `entity`, `interface`), then let AI extend it during
   TBox alignment/evolution (ADR-0011) as evidence demands.

**How to measure:** For a new domain, compare the quality of the resulting ABox
(validity against the TBox, coverage of gold-set terms) and the human/AI effort
to reach a usable TBox. The hybrid is expected to win on effort while keeping
quality.

**Status:** Not yet run. Outcome to be recorded in an ADR (see ADR-0011).
