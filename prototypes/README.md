# Prototypes

Throwaway prototypes for quick evaluation of open architecture questions.
**Skip TDD here** — the goal is fast signal, not production code.

Each prototype should have its own `README.md` stating:
- the question being evaluated
- the options compared
- the measured result

After a decision, record the outcome in an ADR and archive/delete the
prototype (keep it in git history or a branch).

See `AGENTS.md` §1.3.

## Current prototypes

| Prototype | Question | Related ADR |
|-----------|----------|-------------|
| `domain-detection/` | Keyword vs. LLM vs. hybrid domain auto-detection | ADR-0011 |
| `tbox-bootstrap/` | Curated vs. AI-generated vs. hybrid TBox bootstrap | ADR-0011 |
| `abox-merge/` | Deterministic vs. LLM-judged vs. hybrid ABox merge | ADR-0011 |
| `graph-storage/` | JSON vs. NetworkX vs. RDF vs. graph-DB storage | ADR-0013 |
| `consolidation/` | How to merge near-duplicate ontology terms (normalization vs. fuzzy vs. abbr-linking) | — |
