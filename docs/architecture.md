# onto3gpp — High-Level Architecture

> **Status:** Living document. Update as the architecture evolves.
> **Last updated:** 2026-08-24

## 1. Vision

A **domain-general pipeline** that constructs an **ontology-guided RAG** system
with an AI assistant, usable **without AI** (or with cheap AI) at runtime to
minimize cost.

The core design principle (from the brainstorm):

> **LLM as an offline knowledge engineer and judge; ontology as the persistent
> reasoning layer; deterministic NLP as the runtime interface; conventional
> search as the retrieval engine.**

Two deliberate departures from the original brainstorm:

1. **No human-in-the-loop.** The bootstrap and iterative improvement loops are
   gated by **AI-as-judge** against a ground-truth evaluation set, not by human
   review. Humans set policy and thresholds; AI executes the loop.
2. **Domain-general.** 3GPP is the first domain, but every AI prompt, schema,
   and pipeline stage is driven by a **domain pack** (prompt templates + config),
   never hard-coded to 3GPP.

---

## 2. High-Level Architecture

```
                    OFFLINE (AI-assisted, AI-judged)
┌──────────────────────────────────────────────────────────────────┐
│  Domain documents (.docx / .pdf / text)                          │
│        │                                                         │
│        ▼                                                         │
│  Document Parser & Structure Extractor                           │
│        │                                                         │
│        ▼                                                         │
│  Candidate Term / Relation Extractor (rules + LLM)               │
│        │                                                         │
│        ▼                                                         │
│  Ontology Candidate Store (JSON / graph)                         │
│        │                                                         │
│        ▼                                                         │
│  AI-as-Judge Gate  ◄── ground-truth gold set + provenance        │
│        │                                                         │
│        ▼                                                         │
│  Ontology Compiler                                               │
│        │                                                         │
│        ├─► Dictionary / Aho-Corasick Trie                        │
│        ├─► Relation rules + weights                              │
│        ├─► Intent patterns                                       │
│        └─► Spec / clause index metadata                          │
│        │                                                         │
│        ▼                                                         │
│  Versioned Knowledge Pack (Rel-XX.bin / .json + .trie)           │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
                    RUNTIME (CPU-only, AI-free)
┌──────────────────────────────────────────────────────────────────┐
│  User Query                                                      │
│        │                                                         │
│        ▼                                                         │
│  Normalizer                                                      │
│        │                                                         │
│        ▼                                                         │
│  Deterministic NER (Aho-Corasick + rules)                        │
│        │                                                         │
│        ▼                                                         │
│  Concept Resolver + Ambiguity Ranking                            │
│        │                                                         │
│        ▼                                                         │
│  Intent Detector (pattern-based)                                 │
│        │                                                         │
│        ▼                                                         │
│  Ontology Reasoner → Query IR / Search Plan                      │
│        │                                                         │
│        ▼                                                         │
│  BM25 / Lexical Search (+ optional light vectors)                │
│        │                                                         │
│        ▼                                                         │
│  Relationship-aware + Structure-aware Reranker                   │
│        │                                                         │
│        ▼                                                         │
│  Ranked Results + Explanation Trace                              │
└───────────────────────────┬──────────────────────────────────────┘
                            │
                            ▼
              RECURSIVE IMPROVEMENT LOOP (AI-judged)
  Search logs / gold queries → offline analysis → AI proposals
  → AI-as-judge → new pack → re-evaluate metrics → promote
```

---

## 3. The Two Key Design Decisions

### 3.1 AI-as-Judge (removes human-in-the-loop)

The original brainstorm had a "Human Review Gate". We replace it with an
**AI-as-Judge** gate:

- **Bootstrap:** AI extracts candidate terms/relations, then **judges its own
  output** against the ground-truth gold set + provenance checks. Only
  candidates passing the judge's confidence threshold enter the ontology.
- **Iterative improvement:** AI analyzes search logs, proposes changes, judges
  them against a hold-out eval set, and promotes only if metrics improve.
- **Humans set policy** (thresholds, gold set, domain pack) but do **not**
  review every candidate.

**Why this is safe:** the judge is not free-form opinion — it is scored against
a **ground-truth gold set** with standard IR metrics (MRR, NDCG, Recall@k). A
hallucinated or wrong candidate that degrades metrics is rejected by the loop
itself. The judge's decisions are auditable via provenance and eval logs.

**Open questions (see ADRs):**
- How to calibrate the judge's confidence threshold?
- How to prevent the judge from being self-referential (judging its own
  hallucinations as correct)?
- What is the minimum gold-set size for reliable gating?

### 3.2 Domain-General Pipeline

Every AI prompt and pipeline stage is driven by a **domain pack**:

```
docs/domain/
├── _template/          # template for new domains
│   ├── prompts/        # AI prompt templates (parameterized)
│   └── config.yaml     # domain config (concept types, relations, intents)
└── 3gpp/               # the first concrete domain
    ├── prompts/
    └── config.yaml
```

The pipeline code reads the domain pack and never hard-codes 3GPP terms. To
adapt to a new domain, you create a new domain pack (copy `_template`, fill in
prompts + config) — no code changes.

**Open questions (see ADRs):**
- How much of the pipeline is truly domain-agnostic vs. domain-specific?
- What is the minimal domain-pack schema?

---

## 4. Data Model (domain-general)

The data model is domain-agnostic; the domain pack defines the allowed
`concept_type`, `relation_type`, and `intent` values.

```python
# Concept
{
  "id": "concept.pdu_session",
  "canonical": "PDU Session",
  "type": "procedure|network_function|ie|interface|...",  # from domain pack
  "aliases": ["PDU session", "PDU sessions"],
  "abbreviations": ["PDU"],
  "parents": ["concept.session_management"],
  "related": [{"id": "concept.smf", "rel": "uses", "weight": 0.55}],
  "specs": [{"number": "23.501", "clause": "5.6", "release": "Rel-18"}],
  "introduced_in": "Rel-15",
  "provenance": [{"spec": "23.501", "clause": "5.6.1", "text_snippet": "..."}]
}

# Term (surface form → concept)
{
  "surface": "Access and Mobility Management Function",
  "normalized": "access and mobility management function",
  "concept_id": "concept.amf",
  "priority": 1.0,
  "term_type": "full_name|abbr|alias|morph"
}

# Relation
{
  "source": "concept.smf",
  "rel": "selects",
  "target": "concept.upf",
  "weight": 0.70,
  "provenance": [...]
}

# SearchRule (deterministic expansion)
{
  "trigger": "concept.pdu_session_establishment",
  "add": [
    {"concept": "concept.smf", "weight": 0.55},
    {"term": "PDU Session Establishment Request", "weight": 0.85}
  ],
  "conditions": {"intent": ["PROCEDURE", "HOW"]}
}
```

---

## 5. Runtime Query Path (CPU-only, AI-free)

```python
def process_query(q: str, pack: KnowledgePack) -> SearchPlan:
    q_norm = normalize(q)                          # lower, hyphen, plural, etc.
    spans = pack.automaton.find(q_norm)            # Aho-Corasick
    concepts = resolve_ambiguity(spans, pack)      # confidence ranking
    intent = detect_intent(q_norm, pack.patterns)
    expanded = reason(concepts, intent, pack.graph, pack.rules)
    return SearchPlan(
        primary_terms=...,
        secondary=...,
        boosts=...,          # specs, clauses, relations
        proximity_groups=...,
        explanation=...
    )
```

---

## 6. Tech Stack (initial)

| Component              | Choice                          | Why |
|------------------------|---------------------------------|-----|
| Language               | Python 3.11+                    | Ecosystem, speed of dev |
| CLI                    | `click` or `tyro`               | Simple, typed |
| Multi-pattern match    | `pyahocorasick`                 | Fast, CPU, serializable |
| Graph                  | NetworkX (small) or pure dict   | Lightweight reasoning |
| Document parse         | `python-docx` + custom clause walker | 3GPP structure |
| LLM offline            | LiteLLM (OpenAI / local vLLM)   | Swappable, domain-general |
| Search                 | `rank_bm25` or Elasticsearch    | Proven baseline |
| Storage of packs       | pickle / msgpack + JSON sidecar | Fast load |
| Evaluation             | custom + `ir_measures`          | Standard IR metrics |
| Versioning             | Git + semantic pack tags        | Traceability |

> These are initial choices, not commitments. Each is a candidate for a
> prototype/ADR if an open question arises.

---

## 7. Evaluation Harness (first-class citizen)

The eval harness is **mandatory** before any pack is promoted:

- **Gold set:** `data/gold_queries.jsonl` — real queries + relevant clause IDs.
- **Metrics:** MRR, NDCG@k, Recall@k.
- **Hold-out set:** a portion of the gold set reserved for judging improvement
  proposals (prevents overfitting the loop to the training gold set).
- **Regression:** every stage re-runs the full eval to catch regressions.

---

## 8. Recursive Improvement Loop (AI-judged)

```
while True:
  1. Collect search logs + failed / reformulated queries
  2. Offline analysis:
     - surface forms that never matched
     - high-click / low-score mismatches
     - frequent co-occurrences not yet in relations
  3. LLM proposes new terms / aliases / relations (with confidence + provenance)
  4. AI-as-judge scores proposals against hold-out eval set
  5. Merge accepted proposals into ontology (version bump)
  6. Re-compile pack
  7. Re-run eval on gold set + hold-out queries
  8. If ΔMRR / ΔRecall@10 > threshold → promote pack
     else keep previous pack and log regression
```

---

## 9. Roadmap Summary

See `docs/roadmap.md` for the full staged plan. High-level:

| Stage | Focus | Gate |
|-------|-------|------|
| 0 | Baseline: parse + index + BM25 | Baseline metrics recorded |
| 1 | Terminology: extract + compile dictionary | Term-expansion lift |
| 2 | Ontology + relations | Relationship-aware ranking |
| 3 | Intent + structure boosts | Intent-aware results |
| 4 | AI-as-judge improvement loop | Closed-loop improvement |
| 5 | Optional small CPU NER model | Residual ambiguity |

---

## 10. Open Questions (tracked in ADRs)

- Judge calibration & self-referentiality (ADR-0002).
- Domain-pack schema & pipeline generality boundary (ADR-0003).
- Runtime fallback chain (Level 0–4) design.
- Storage & packaging format for knowledge packs.
- Whether/when to add vector search.
