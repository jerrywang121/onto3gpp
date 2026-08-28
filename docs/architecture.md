# onto3gpp — High-Level Architecture

> **Status:** Living document. Update as the architecture evolves.
> **Last updated:** 2026-08-25

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

### 1.1 Offline AI vs. CPU-only runtime (clarified)

The app has two distinct execution surfaces:

- **Offline AI (knowledge engineering).** AI is used to *extract* terms and
  relations and to *construct/refine* the ontology and knowledge graphs. This
  runs during ingestion and improvement, never on the query path.
- **CPU-only runtime (query).** For a query, AI is **not** used for the core
  search operation. Synthesizing search results into a natural-language answer
  is *post-processing* and may optionally use AI, but the core retrieval
  (NER → intent → reason → BM25 → rerank) is deterministic and AI-free.

### 1.2 Two-level graph model (TBox + ABox)

Each domain maintains **two levels of graph**:

- **Top-level ontology graph (TBox / schema).** Nodes are **concept types**
  (e.g. `network_function`, `procedure`); edges are **relation types**
  (e.g. `uses`, `selects`) connecting concept types. This is the **blueprint /
  constraint** that guides later extraction and construction of the low-level
  knowledge graph.
- **Low-level knowledge graph (ABox / instances).** Nodes are **concrete
  concept objects** (e.g. `SMF`, `PDU Session`); edges are typed relations
  between them, with **metadata** and **references to the original documents**
  (provenance).

Both graphs are **domain-specific** — they cover the domain's concepts and
relations, not general terms. The TBox constrains what the ABox may contain;
the ABox grounds the TBox in concrete, retrievable instances.

---

## 2. High-Level Architecture

```
                    OFFLINE (AI-assisted, AI-judged)
┌──────────────────────────────────────────────────────────────────┐
│  Domain documents (.docx / .pdf / text)                          │
│        │                                                         │
│        ▼                                                         │
│  Domain Auto-Detection (if not specified)                         │
│        │                                                         │
│        ▼                                                         │
│  TBox Bootstrap (create top-level ontology if absent)            │
│        │                                                         │
│        ▼                                                         │
│  Document Parser & Structure Extractor                           │
│        │                                                         │
│        ▼                                                         │
│  Candidate Term / Relation Extractor (rules + LLM)               │
│        │                                                         │
│        ▼                                                         │
│  TBox Alignment (check against top-level ontology)              │
│        │                                                         │
│        ├─► conforms ──► ABox Merge (dedupe / conflict-resolve)    │
│        └─► new type/relation/connection ──► TBox Evolution        │
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
│        │                                                         │
│        ▼  (optional, post-processing — NOT core search)          │
│  Answer Synthesis (AI, optional)                                 │
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

### 3.1.1 External AI Hooks (ADR-0004, ADR-0012, ADR-0015)

The AI-as-judge / AI-extraction / ingestion / improvement-loop paths are
**optional** and driven by a configurable LLM client (`src/onto3gpp/llm.py`,
LiteLLM-backed). The app configures providers/models/embeddings via the
**app-level** `config/app.yaml` (ADR-0015), not the domain pack. Domain packs
keep only intents/patterns/metadata/`judge_threshold` and stay portable. The
app is deterministic by default (`llm.enabled: false` in `config/app.yaml`);
the runtime query path is always AI-free.

**Multi-model routing (ADR-0012) with DRY providers (ADR-0015).** Different
pipeline tasks have different cost/quality needs, so `config/app.yaml` owns a
**`providers:`** map (per-provider wiring) and an **`llm:`** task → model
routing map that just references `provider: <name>`:

```yaml
providers:
  openai: {api_key_env: OPENAI_API_KEY}
  ollama: {api_base: http://localhost:11434}
llm:
  enabled: false
  default: {provider: openai, model: gpt-4o-mini}
  models:
    extract:       {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
    judge:         {provider: openai, model: gpt-4o,      temperature: 0.0, max_tokens: 1024}
    align:         {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
    merge:         {provider: ollama, model: llama3}
    domain_detect: {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 256}
    improve:       {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
```

Each task resolves to a model; the `LLMClient` becomes a router. A task with no
explicit model falls back to a default. Consumers:

- `llm_judge_candidate` — AI-as-judge with deterministic fallback.
- `propose_improvements` / `apply_proposals` — the improvement loop.
- `ingest` — domain detect, TBox bootstrap, extract, align, evolve, merge.

### 3.2 Domain-General Pipeline

Every AI prompt and pipeline stage is driven by a **domain pack**:

```
config/
└── app.yaml            # app-level AI config (llm: enabled/default/models + embed: kind/dim — ADR-0015)
docs/domain/
├── _template/          # template for new domains
│   ├── prompts/        # AI prompt templates (parameterized)
│   ├── config.yaml     # domain config (intents, patterns, metadata, judge_threshold — no llm/embed)
│   └── tbox.yaml       # top-level ontology (TBox): concept/relation types + constraints
└── 3gpp/               # the first concrete domain
    ├── prompts/
    ├── config.yaml     # domain-only (no llm/embed)
    └── tbox.yaml
```

The pipeline code reads the domain pack and never hard-codes 3GPP terms. To
adapt to a new domain, you create a new domain pack (copy `_template`, fill in
prompts + config) — no code changes.

**Open questions (see ADRs):**
- How much of the pipeline is truly domain-agnostic vs. domain-specific?
- What is the minimal domain-pack schema?

### 3.3 AI-Assisted Knowledge Ingestion (TBox + ABox build/refine)

Ingestion is where AI does its primary knowledge-engineering work. The flow
is deterministic-first with AI filling the gaps, and every AI decision is
gated by the AI-as-judge (ADR-0001) and evidence-based evolution (ADR-0005).

```
input doc
   │
   ▼
1. Domain Auto-Detection        (AI if not specified by the user)
   │
   ▼
2. TBox Bootstrap               (create top-level ontology if absent)
   │
   ▼
3. Parse + Structure Extract    (deterministic)
   │
   ▼
4. Extract terms + relations    (rules + AI)
   │
   ▼
5. TBox Alignment               (check against top-level ontology)
   │
   ├─► conforms ────────────────► 6a. ABox Merge (dedupe / conflict-resolve)
   └─► new type/rel/connection ─► 6b. TBox Evolution (gated, auditable)
   │
   ▼
7. AI-as-Judge Gate             (against gold set + provenance)
   │
   ▼
8. Compile → Knowledge Pack      (dictionary, rules, intents, index)
```

**Where AI is used (offline only):**
- **Domain auto-detection** — if the user doesn't specify the domain, classify
  the document's domain (prototype: keyword vs. LLM classifier).
- **TBox bootstrap** — if no top-level ontology exists, create one. Curated in
  the domain pack by default; AI may propose extensions (ADR-0011).
- **Term/relation extraction** — rules first, AI for the residual (existing
  `extract/terms.py`, `extract/relations.py` + LLM prompts).
- **TBox alignment** — check extracted entries against the TBox; flag new
  concept types, relation types, or connections.
- **TBox evolution** — if new types/connections are discovered with sufficient
  evidence, update the TBox (gated, auditable).
- **ABox merge / conflict resolution** — add new terms/relations to the
  low-level KG; merge similar objects/relations; resolve conflicts
  (deterministic similarity first, AI-judge for ambiguous cases).
  The promoted path (`src/onto3gpp/ingest/merge_judge.py` +
  `merge_abox_with_judge`, ADR-0014) does **embedding-guided retrieval**
  then an **LLM judge** over the top-k neighbours only (bounded cost).
  Default embedding is CPU-only `hash` (384-d char n-grams, stdlib, no
  download); swappable to `tfidf` / `ollama` (e.g. `embeddinggemma:300m`
  768-d, `http://localhost:11434/api/embed`) / `api` (OpenAI-compat)
  via the domain pack `embed:` block (`threshold 0.25`, `top_k 5`). The
  judge prompt distinguishes timers/DCI single-char variants (distinct)
  from hyphen/space/case variants (same); hallucinated targets fall back
  to ADD and `enabled: false` falls back to deterministic normalization.
  This is **offline ingest only** — the runtime query path stays
  AI-free and CPU-only.

**Where AI is NOT used:**
- The runtime query path (core search) is always deterministic and AI-free.
- Answer synthesis is optional post-processing, not core search.

---

## 4. Data Model (domain-general, two-level)

The data model is domain-agnostic; the domain pack defines the allowed
`concept_type`, `relation_type`, and `intent` values, and the **TBox** defines
which relation types may connect which concept types.

### 4.1 Top-level ontology (TBox / schema)

The TBox is the **blueprint / constraint** for the ABox. It is curated in the
domain pack and evolved by AI only when evidence demands (see §4.4).

```python
# ConceptType (TBox node)
{
  "id": "network_function",
  "label": "Network Function",
  "description": "A 3GPP network function (AMF, SMF, UPF, ...)",
  "parent": null,                 # optional subtyping
  "constraints": {"min_relations": 0}
}

# RelationTypeConstraint (TBox edge)
{
  "source_type": "network_function",
  "rel": "uses",
  "target_type": "network_function",
  "description": "A network function uses another network function",
  "weight": 0.7
}
```

The TBox is serialized as `tbox.yaml` in the domain pack, and the `ingest`
command writes the evolved TBox back to it. It answers: *"is a
`network_function` allowed to `select` a `procedure`?"*

### 4.2 Low-level knowledge graph (ABox / instances)

The ABox holds concrete concept objects, typed relations, metadata, and
provenance back to the source documents. This is what the runtime consumes.

```python
# Concept (ABox node)
{
  "id": "concept.pdu_session",
  "canonical": "PDU Session",
  "type": "procedure|network_function|ie|interface|...",  # from TBox
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

# Relation (ABox edge)
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

### 4.3 TBox ↔ ABox relationship

- The **TBox constrains the ABox**: every ABox concept's `type` must be a TBox
  concept type; every ABox relation's `(source.type, rel, target.type)` must be
  a TBox relation-type constraint.
- The **ABox grounds the TBox**: concrete instances and their provenance make
  the schema meaningful and retrievable.
- **Domain-specific only**: both graphs cover the domain's concepts/relations,
  not general terms. General-language terms are excluded at extraction time.

### 4.4 TBox evolution

The TBox is **curated by default** (hand-authored in the domain pack) and
**evolved by AI only when evidence demands**:

- During ingestion, if extraction discovers a **new concept type**, a **new
  relation type**, or a **new connection** between existing types, the
  alignment step flags it.
- The AI-as-judge gate (ADR-0001) decides whether the evidence is strong enough
  to evolve the TBox. Evolution is **gated and auditable** (ADR-0005,
  ADR-0011): a TBox change is promoted only if it improves (or doesn't regress)
  the eval metrics and is grounded in provenance.
- Humans set policy (which types/relations are allowed, evolution thresholds);
  AI executes the loop.

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
| Graph (TBox + ABox)    | JSON (v1); NetworkX / RDF / graph DB as prototype alternatives | Lightweight, reuses serialization |
| Document parse         | `python-docx` + custom clause walker | 3GPP structure |
| LLM offline            | LiteLLM (OpenAI / local vLLM / ollama) | Swappable, domain-general, multi-model routing |
| Search                 | `rank_bm25` or Elasticsearch    | Proven baseline |
| Storage of packs       | pickle / msgpack + JSON sidecar | Fast load |
| Evaluation             | custom + `ir_measures`          | Standard IR metrics |
| Versioning             | Git + semantic pack tags        | Traceability |

> These are initial choices, not commitments. Each is a candidate for a
> prototype/ADR if an open question arises. Graph storage is an open question
> (ADR-0013) — JSON for v1, with NetworkX / RDF / graph-DB as prototype
> alternatives.

---

## 7. Evaluation Harness (first-class citizen)

The eval harness is **mandatory** before any pack is promoted:

- **Gold set:** `data/gold_queries.jsonl` — real queries + relevant clause IDs.
- **Metrics:** MRR, NDCG@k, Recall@k.
- **Hold-out set:** a portion of the gold set reserved for judging improvement
  proposals (prevents overfitting the loop to the training gold set).
- **Regression:** every stage re-runs the full eval to catch regressions.
- **TBox/ABox quality:** ingestion stages additionally measure TBox constraint
  conformance (share of ABox entries that satisfy the TBox) and merge precision
  (share of merged objects that are true duplicates), so the two-level graph
  stays coherent as it grows.

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

The improvement loop operates on the **ABox** (concrete terms/relations). TBox
evolution is a separate, more conservative path (ADR-0011) that only fires
when ingestion discovers genuinely new concept types, relation types, or
connections.

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
| 6 | Web explorer | Interactive exploration |
| 7 | Two-level graph (TBox + ABox) + storage | TBox constraint conformance |
| 8 | AI provider/model configuration surface | Multi-model routing works |
| 9 | AI-assisted knowledge ingestion | End-to-end ingest → TBox/ABox build/refine |
| 10 | AI-as-judge weighted path search (later phase) | Inference-time AI gating |

---

## 10. Open Questions (tracked in ADRs)

- Judge calibration & self-referentiality (ADR-0002).
- Domain-pack schema & pipeline generality boundary (ADR-0003).
- Runtime fallback chain (Level 0–4) design.
- Storage & packaging format for knowledge packs.
- Whether/when to add vector search.
- Graph storage format at scale (ADR-0013).
- Domain auto-detection method (prototype: keyword vs. LLM).
- TBox bootstrap method (prototype: curated vs. AI-generated).
- ABox merge/conflict-resolution method (prototype: deterministic vs. AI-judged).
