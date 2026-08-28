# Prototype: Embedding-assisted ABox merge (AI-assist merge)

**Question:** The pipeline struggles to identify near-duplicate terms/concepts and decide whether a newly extracted term should be **added** as a fresh concept or **merged** with an existing one (as an alias/surface). Can an embedding-based retrieval + AI judge solve this cheaply and correctly?

**Prior art:** `abox-merge` compared deterministic vs LLM vs hybrid duplicate detection (no embedding retrieval). `consolidation` showed deterministic normalization is the only safe auto-merge (≈21 concepts collapsed) and Dice-bigram fuzzy merge is **unsafe** for 3GPP (single-char flips meaning: `ACTIVE`/`INACTIVE`, `T3444`/`T3445`, `C1-174182`/`C1-174183` all score ≥0.86). Abbreviation→full-form by initials was also unsafe. The safe signal is *provenance-grounded* (`Full Form (ABBR)` parentheses). This prototype adds a **retrieval** layer (embedding) before the judge, so the judge only sees a small candidate set.

## Design

### Flow

```
new CandidateTerm
   │
   ▼
 embed(new.canonical + aliases) ─┐
                                 ├─► cosine top-k over existing concept embeddings
 existing concept embeddings ─────┘        (threshold τ, k=5)
                                 │
                                 ▼
                        candidate neighbours (0..k)
                                 │
                                 ├── 0 neighbours ──► ADD
                                 │
                                 └── 1..k neighbours ──► LLM judge (merge vs add)
                                                           │
                                              ┌────────────┼────────────┐
                                              ▼            ▼            ▼
                                           MERGE(target)  ADD      (defer/ask)
```

Only the top-k neighbours are shown to the judge, keeping prompt cost low.
If the LLM is disabled, a deterministic fallback (exact normalized match) decides.

### Embedding interface — pluggable

```python
class Embedder(Protocol):
    dim: int
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Two local CPU-only implementations (zero heavy deps) and one API implementation share the interface:

| Impl | Class | How | Deps | When to use |
|------|-------|-----|------|-------------|
| **Hash** (default) | `HashEmbedder` | char 3–5-gram hashing → 384-d L2-normalized vector, random-projection seeded hash | stdlib only (`hashlib`, `math`) | default local, instant, no model download, captures lexical variants (`NGAP`/`NG-AP`, `E-UTRAN`/`EUTRAN`) |
| **TF-IDF** (optional) | `TfIdfEmbedder` | TF-IDF over existing corpus (word + char ngrams), cosine | stdlib (or `sklearn` if present) | when corpus is stable, slightly better recall |
| **API** | `ApiEmbedder` | POST to customer `api_base` (OpenAI-compatible `/v1/embeddings`) with `model`, `api_key` | `urllib` / `requests` | swap in a cloud embedding (e.g. `text-embedding-3-small`, Cohere) without code change |

Factory: `get_embedder(cfg: dict) -> Embedder` — `cfg = {"kind": "hash"|"tfidf"|"api", "dim": 384, "api_base": ..., "model": ...}`. Swapping is a one-line config change (or `domain pack config.yaml` `embed:` block).

The prototype also ships a thin cosine index (`EmbeddingIndex`) — brute-force in memory, replaceable with FAISS/Chroma later. Production path is `src/onto3gpp/embed/` + `src/onto3gpp/ingest/merge.py` hook.

### Judge

`MergeJudge` wraps the existing `LLMClient` / `LLMConfig` (ADR-0012). Prompt: given `new_term` (canonical + aliases + type + provenance) and each neighbour (canonical + aliases + type), answer JSON `{"decision": "MERGE"|"ADD", "target": "<id|null>", "reason": "..."}`. When `llm.enabled=false`, falls back to: MERGE iff normalized canonicals equal (`casefold`, hyphens→spaces, collapse ws).

## Options compared

1. **Deterministic normalization** (baseline) — merge iff normalized forms equal.
2. **Embedding retrieval + heuristic judge** — Hash/TF-IDF top-k + normalized-match judge (no LLM, tests retrieval quality alone).
3. **Embedding retrieval + LLM judge** — Hash/TF-IDF top-k + LLM judge (hybrid; LLM sees only neighbours).
4. **(Reference) API embedding + LLM judge** — same as (3) but with a cloud embedding; measured only if `api_base` is configured.

## How to measure

*Labelling:* a hand-checked set of 30 pairs derived from `data/reference/dict_38300.json` (329 concepts, 552 surfaces) — 15 true duplicates (should MERGE) and 15 true distinct (should ADD), including the hard negatives from `consolidation` (`ACTIVE`/`INACTIVE`, `T3444`/`T3445`, timer IDs, `DCI-1-0`/`DCI-0-1`, `MPS`/`MCPTT` etc.).

*Metrics:* duplicate-detection precision/recall/F1, merge-target accuracy (did we pick the right neighbour), wall-clock per term (hash vs API), and LLM cost (tokens / calls). Also report retrieval recall@k (is the true target in top-k).

*Success gate:* embedding+LLM matches or beats deterministic F1 on hard cases, and retrieval recall@5 ≥ 0.9, while keeping p50 latency < 10 ms for the local embedding path and < 1 LLM call per new term.

## Files

| File | Purpose |
|------|---------|
| `embed.py` | `Embedder` protocol, `HashEmbedder`, `TfIdfEmbedder`, `ApiEmbedder`, `EmbeddingIndex`, factory |
| `merge.py` | `MergeJudge`, `decide(new_term, index, judge)` pipeline |
| `evaluate.py` | labelled pairs + harness, prints metrics |
| `report.md` | measured results (filled after running `evaluate.py`) |

## Status

Prototype scaffolded; run `python evaluate.py` (no extra deps) for the offline evaluation. LLM path runs when `llm.enabled` is set; otherwise the report shows retrieval-only results and notes the LLM gate.

Production promotion (if gated metrics pass): move `embed.py`→`src/onto3gpp/embed/`, wire `EmbeddingIndex` into `src/onto3gpp/ingest/merge.py`, expose `embed:` in domain-pack `config.yaml`, and record the outcome in a new ADR.
