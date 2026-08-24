# ADR-0003: Compiled Terminology Dictionary for Runtime NER

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 1 (Terminology)

## Context

The runtime query path must be deterministic, CPU-only, and AI-free. To
support term-aware search (abbreviation↔full-name resolution, alias→canonical
mapping), the runtime needs a way to recognize ontology terms in queries and
documents. We need a compiled artifact that ships to the runtime without any
AI dependency.

## Decision

Compile gated candidate terms into a **dictionary backed by an Aho-Corasick
automaton** (`pyahocorasick`). The dictionary maps every surface form
(canonical + aliases + abbreviations) to a canonical term. It is serialized to
JSON for the runtime.

- **Extraction** (offline, AI-free rules): abbreviations, title phrases,
  paren-linked full names.
- **Judge gate** (offline): deterministic support/accuracy/non-redundancy
  scoring; adaptive weighting for bootstrap vs. gold-evidence mode.
- **Compile** (offline): build the Aho-Corasick automaton + dictionary.
- **Runtime NER**: case-insensitive automaton match → canonical term.
- **Query expansion**: add canonical terms + surface forms to the BM25 query.

## Consequences

- **Positive:** deterministic, fast, CPU-only runtime NER; no AI cost at
  query time; serializable artifact.
- **Negative:** rules-based extraction is limited (no deep semantics); the
  dictionary only covers terms seen in the source corpus.
- **Trade-off:** an LLM extraction path can be added later (prompt template
  exists) but the runtime stays deterministic.

## Alternatives Considered

- **LLM NER at runtime** — rejected: violates the "AI offline, deterministic
  runtime" principle and adds cost/latency.
- **Regex-only matching** — rejected: no alias→canonical resolution, slower
  for large dictionaries.
- **Embedding-based NER** — rejected: needs a model at runtime, not CPU-only.

## Open Questions

- Does term expansion show a measurable lift on real 3GPP documents?
- Should the dictionary be versioned per release (see Stage 2 ontology
  versioning)?
