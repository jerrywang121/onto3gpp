# ADR-0008: Level 0-4 NER Fallback Chain (Small CPU Model)

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 5 (Optional Small CPU NER Model)

## Context

The runtime NER path (Stage 1) resolves query terms via a compiled dictionary
(Aho-Corasick exact match). This handles abbreviations and aliases that are in
the dictionary, but leaves **residual ambiguity**: a query may use a surface
form that is not in the dictionary (e.g. "qos flow" when the canonical is "QoS
Flow Mapping"), or a phrase that only partially matches a concept. The runtime
must stay deterministic and CPU-only (no AI cost), so we need a cheap fallback
chain that resolves these ambiguous phrases.

## Decision

Add a **Level 0-4 NER fallback chain** (`src/onto3gpp/runtime/ner_chain.py`):

- **L0 dictionary** — exact Aho-Corasick match against the compiled dictionary.
- **L1 rules** — abbreviation / title-phrase rules (from the extractor).
- **L2 small CPU model** — a deterministic fuzzy matcher for **short ambiguous
  phrases** (≤ 4 tokens). Uses **token containment**: every query token must
  appear in the concept canonical's tokens. This resolves "qos flow" → "QoS
  Flow Mapping" but not "handover procedure" → "Random Access Procedure"
  (which merely shares a common word). No neural network, no AI cost.
- **L3 resolver** — alias → canonical resolution via the ontology.
- **L4 reasoning** — ontology graph expansion (1-hop neighbors of resolved
  concepts).

Each level is cheaper and more precise than the next; we only fall through to a
higher level when lower levels fail. The chain is domain-agnostic — it operates
on the dictionary + ontology, not on 3GPP terms.

**Integration:** In `search_structure`, only **L2 and L3** resolutions
contribute query tokens. L0 (dictionary exact) and L4 (ontology reasoning) are
already handled by `reason()`, so adding them again would pollute the query
with hub-related terms and regress ranking. The `--chain` flag on `eval`
enables the chain.

## Alternatives considered

1. **Bigram Dice similarity alone.** Rejected: too loose — it matched unrelated
   concepts that merely share a common word (e.g. "handover procedure" matched
   "Random Access Procedure"). Token containment is the precise signal.
2. **A real neural NER model (e.g. spaCy/transformers).** Rejected: violates
   the CPU-only, zero-AI-cost runtime principle (AGENTS.md §0.1). The token-
   containment matcher is deterministic and dependency-free.
3. **Apply the chain at all levels to query tokens.** Rejected: L4 expansion
   added hundreds of hub-related terms (e.g. 1-hop neighbors of "UE"), which
   polluted the query and regressed MRR from 0.854 to 0.467.

## Consequences

- The chain matches the Stage 3 baseline on the real gold set (MRR 0.854) with
  **no regression**, and resolves residual ambiguity the baseline cannot (e.g.
  "qos flow" → "QoS Flow Mapping" surfaces clause 6.2.5.2).
- CPU cost is negligible: token containment is O(query_tokens × canonicals),
  all in-memory, no model load.
- The chain is a **fallback**, not a replacement — it only fires when the
  dictionary and reasoner don't already resolve a term.
