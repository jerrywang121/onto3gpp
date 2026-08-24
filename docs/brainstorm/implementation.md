**Review & Updated Design + Python CLI for the 3GPP Ontology-Guided Search Pipeline**

## 1. Review of the Original Suggestion

**Strengths (keep these)**
- Clear offline-AI / runtime-deterministic split.
- Concepts separated from surface terms + weighted expansion.
- Multi-layer deterministic NER (exact → normalize → phrase/Aho-Corasick).
- Intent + relationship-aware ranking.
- Provenance, release versioning, document structure awareness.
- Closed-loop improvement from search logs.
- Phased roadmap.

**Weaknesses / gaps to fix**
- Too abstract; no concrete data model, schemas, or CLI entry points.
- “Recursive improvement” is only sketched; needs an explicit feedback + validation loop with metrics and human-in-the-loop gates.
- Runtime still risks becoming complex; needs a strict “Level 0–4” fallback chain and a single compile step that produces a binary knowledge pack.
- No mention of evaluation harness (gold queries + metrics) as a first-class citizen.
- Ontology growth can explode; needs controlled expansion + confidence/provenance thresholds.
- Document parsing of real 3GPP .docx/.pdf is non-trivial; must be part of the pipeline.
- Missing concrete tech choices for storage, matching, and packaging.

**Updated core principle**
> LLM acts only as an offline knowledge engineer. Everything that touches a live query is deterministic, explainable, and runs on CPU from a versioned knowledge pack. Improvement is recursive but gated by metrics + human review.

---

## 2. Updated High-Level Architecture

```
OFFLINE (AI-assisted, human-gated)
┌──────────────────────────────────────────────────────────────┐
│  3GPP Specs (.docx / .pdf / text)                            │
│         │                                                    │
│         ▼                                                    │
│  Document Parser & Structure Extractor                       │
│         │                                                    │
│         ├─► Candidate Term / Relation Extractor (rules+LLM)  │
│         │                                                    │
│         ▼                                                    │
│  Ontology Candidate Store (JSON / graph)                     │
│         │                                                    │
│         ▼                                                    │
│  Validation + Human Review Gate                              │
│         │                                                    │
│         ▼                                                    │
│  Ontology Compiler                                           │
│         │                                                    │
│         ├─► Dictionary / Aho-Corasick Trie                   │
│         ├─► Relation rules + weights                         │
│         ├─► Intent patterns                                  │
│         └─► Spec / clause index metadata                     │
│         │                                                    │
│         ▼                                                    │
│  Versioned Knowledge Pack (Rel-XX.bin / .json + .trie)       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
RUNTIME (CPU-only, AI-free)
┌──────────────────────────────────────────────────────────────┐
│  User Query                                                  │
│         │                                                    │
│         ▼                                                    │
│  Normalizer                                                  │
│         │                                                    │
│         ▼                                                    │
│  Deterministic NER (Aho-Corasick + rules)                    │
│         │                                                    │
│         ▼                                                    │
│  Concept Resolver + Ambiguity Ranking                        │
│         │                                                    │
│         ▼                                                    │
│  Intent Detector (pattern-based)                             │
│         │                                                    │
│         ▼                                                    │
│  Ontology Reasoner → Query IR / Search Plan                  │
│         │                                                    │
│         ▼                                                    │
│  BM25 / Lexical Search (+ optional light vectors)            │
│         │                                                    │
│         ▼                                                    │
│  Relationship-aware + Structure-aware Reranker               │
│         │                                                    │
│         ▼                                                    │
│  Ranked Results + Explanation Trace                          │
└──────────────────────────────────────────────────────────────┘

RECURSIVE IMPROVEMENT LOOP
Search logs / gold queries → offline analysis → candidate proposals
→ human review → new pack → re-evaluate metrics → deploy
```

Key updates:
- Explicit **Knowledge Pack** as the only runtime artifact.
- **Evaluation harness** is mandatory before any pack is promoted.
- Recursive loop is metric-driven and human-gated.
- Document structure (clause hierarchy) is first-class.

---

## 3. Refined Data Model (Practical First Version)

```python
# Concept
{
  "id": "concept.pdu_session",
  "canonical": "PDU Session",
  "type": "procedure|network_function|ie|interface|...",
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

Runtime pack contains:
- Compiled Aho-Corasick automaton (terms → concept IDs)
- Concept / relation graph (lightweight NetworkX or adjacency dict)
- Intent pattern rules
- Spec metadata index

---

## 4. Python CLI Tool Design: `3gpp-ontology`

A single CLI (`3gpp-onto`) that owns the whole offline pipeline + evaluation + recursive improvement.

### 4.1 Package Layout

```
3gpp_ontology/
├── cli.py                 # entry point (click or tyro)
├── config.py
├── parser/                # 3GPP docx/pdf → structured sections
├── extract/               # candidate terms & relations (rules + LLM)
├── ontology/              # schema, merge, validate, version
├── compile/               # produce knowledge pack (trie, graph, rules)
├── runtime/               # deterministic NER + reasoner (also used for eval)
├── search/                # BM25 + reranker wrappers
├── evaluate/              # gold queries, metrics, regression
├── improve/               # log analysis → proposals → review queue
├── packs/                 # versioned output
└── data/
    ├── gold_queries.jsonl
    └── review_queue/
```

### 4.2 CLI Commands

```bash
# 1. Ingest & parse
3gpp-onto parse --spec-dir ./specs --release Rel-18 --out ./parsed

# 2. Extract candidates (rules first, optional LLM)
3gpp-onto extract --parsed ./parsed --method rules+llm --llm-model gpt-4o \
                  --out ./candidates

# 3. Build / merge ontology
3gpp-onto ontology build --candidates ./candidates --base ./ontology/base.json \
                         --out ./ontology/Rel-18.json

# 4. Human review gate (interactive or batch)
3gpp-onto review --ontology ./ontology/Rel-18.json --queue ./review_queue

# 5. Compile knowledge pack
3gpp-onto compile --ontology ./ontology/Rel-18.json \
                  --out ./packs/Rel-18-v1.pack

# 6. Index documents (structure-aware)
3gpp-onto index --parsed ./parsed --pack ./packs/Rel-18-v1.pack \
                --out ./index/Rel-18

# 7. Evaluate
3gpp-onto eval --pack ./packs/Rel-18-v1.pack --index ./index/Rel-18 \
               --gold ./data/gold_queries.jsonl --metrics mrr,ndcg,recall@5,10

# 8. Recursive improvement cycle
3gpp-onto improve --logs ./logs/search.jsonl --pack ./packs/Rel-18-v1.pack \
                  --propose --out ./candidates/from_logs
# then: review → ontology merge → compile → eval → promote if metrics improve
```

### 4.3 Recursive Improvement Loop (explicit)

```
while True:
  1. Collect search logs + failed / reformulated queries
  2. Offline analysis:
     - surface forms that never matched
     - high-click / low-score mismatches
     - frequent co-occurrences not yet in relations
  3. LLM proposes new terms / aliases / relations (with confidence + provenance)
  4. Write to review_queue (JSON diffs)
  5. Human approves / rejects / edits
  6. Merge into ontology (version bump)
  7. Re-compile pack
  8. Re-run eval on gold set + new hold-out queries
  9. If ΔMRR / ΔRecall@10 > threshold → promote pack
     else keep previous pack and log regression
```

This is the “recursive” part: every production search improves the next offline cycle, but never mutates the live runtime without metrics + human gate.

### 4.4 Runtime Query Path (CPU-only, called from CLI for eval)

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

### 4.5 Recommended Tech Stack

| Component              | Choice                          | Why |
|------------------------|---------------------------------|-----|
| CLI                    | `click` or `tyro`               | Simple, typed |
| Multi-pattern match    | `pyahocorasick`                 | Fast, CPU, serializable |
| Graph                  | NetworkX (small) or pure dict   | Lightweight reasoning |
| Document parse         | `python-docx` + custom clause walker | 3GPP structure |
| LLM offline            | OpenAI / local (vLLM) via LiteLLM | Swappable |
| Search                 | `rank_bm25` or Elasticsearch    | Proven baseline |
| Storage of packs       | pickle / msgpack + JSON sidecar | Fast load |
| Evaluation             | custom + `ir_measures`          | Standard IR metrics |
| Versioning             | Git + semantic pack tags        | Traceability |

### 4.6 Implementation Roadmap (aligned with CLI)

| Phase | CLI focus                          | Goal |
|-------|------------------------------------|------|
| 0     | `parse` + `index` + plain BM25    | Baseline metrics |
| 1     | `extract` (rules) + `compile` dictionary only | Term expansion gain |
| 2     | Full ontology + relations         | Relationship-aware ranking |
| 3     | Intent + structure boosts         | Intent-aware results |
| 4     | `improve` loop + gold set         | Closed-loop recursive improvement |
| 5     | Optional small CPU NER model      | Only for residual ambiguity |

---

## 5. Concrete Next Steps You Can Take Immediately

1. Create a small gold set (100–300 real 3GPP questions + relevant clauses).
2. Implement `parse` + BM25 baseline and measure Recall@10 / MRR.
3. Build a seed ontology manually for the top 200 concepts (AMF, SMF, UPF, PDU Session, Registration, N2, etc.).
4. Implement the Aho-Corasick dictionary path and measure the lift.
5. Only then turn on LLM candidate extraction and the review queue.

Would you like me to:
- Write the actual `cli.py` skeleton + data classes + Aho-Corasick NER code, or
- Produce a detailed JSON schema + example Rel-18 seed ontology for the most important 5GC concepts first?

Either way, the design above is ready to be turned into working code.