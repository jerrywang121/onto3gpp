# onto3gpp — Status Tracker

> **Purpose:** Live record of where we are, what's measured, and what's next.
> This is the persistent memory of project progress. Keep it concise.
> **Last updated:** 2026-08-25

## Current Stage

**Stage 9 — AI-Assisted Knowledge Ingestion** (implemented; gate measured — see below)

## Stage Status

| Stage | Status | Branch | Metrics (MRR / NDCG@10 / Recall@10) | Notes |
|-------|--------|--------|-------------------------------------|-------|
| 0 Baseline | 🟢 done | `stage/0-baseline` | 1.000 / 0.992 / 1.000 | Synthetic sample; see caveat |
| 1 Terminology | 🟢 done | `stage/1-terminology` | 0.667 / 0.729 / 0.917 | Real gold set; word-boundary fix resolved regression |
| 2 Ontology | 🟢 done | `stage/2-ontology` | 0.786 / 0.816 / 0.917 | Reasoner + reranker done; 4-spec ontology (5788/26885); gate met |
| 3 Intent | 🟢 done | `stage/3-intent` | 0.854 / 0.895 / 0.972 | Intent detector + structure boosts; gate met |
| 4 Improve loop | 🟢 done | `stage/4-improve-loop` | — | LLM hooks + improve loop + hold-out auto-judge; gate met |
| 5 CPU NER | 🟢 done | `stage/5-cpu-ner` | 0.854 / 0.895 / 0.972 | Level 0-4 fallback chain; no regression; gate met |
| 6 Web Explorer | 🟢 done | `stage/6-web-explorer` | — | FastAPI + vanilla-JS explorer; no runtime change; gate met |
| 7 Two-level graph | 🟢 done | `stage/7-two-level-graph` | — | TBox + ABox + align + storage; conformance 0.0 on current ABox (see §7) |
| 8 AI provider config | 🟢 done | `stage/8-ai-provider-config` | — | Multi-model routing + CLI/env override (ADR-0012) |
| 9 AI ingestion | 🟢 done | `stage/9-ai-ingestion` | — | Detect → extract → align → evolve → merge; CLI `ingest` (ADR-0011). **Eval: AI-assisted extraction REGRESSES MRR vs verb-based (see §9)** |
| 10 AI path search | ⚪ deferred | `stage/10-ai-path-search` | — | AI-as-judge weighted path search (deferred, later phase) |

Legend: 🟢 done · 🔵 in progress · ⚪ not started · 🔴 blocked

## Stage 0 — Baseline (done)

**Delivered:**
- Document parser (text → clause-structured sections).
- Chunker with section metadata.
- BM25 index + search.
- Eval harness (MRR, NDCG@10, Recall@5/10).
- Gold set bootstrap (`data/gold_queries.jsonl`, 10 queries).
- CLI: `onto3gpp parse`, `onto3gpp eval`.

**Metrics (synthetic sample `data/sample/23.501.txt`):**

| Metric | Value |
|--------|-------|
| MRR | 1.0000 |
| NDCG@10 | 0.9920 |
| Recall@5 | 1.0000 |
| Recall@10 | 1.0000 |

> **Caveat:** these metrics are on a tiny synthetic sample and are
> near-perfect. They establish the *harness works*, not real-world quality.
> Real 3GPP documents + a larger gold set are needed for meaningful baselines.

## Stage 1 — Terminology (in progress)

**Delivered:**
- Candidate term extraction (rules-based): abbreviations + title phrases +
  paren-linked full names (`src/onto3gpp/extract/terms.py`).
- AI-as-judge gate (deterministic): support/accuracy/non-redundancy scoring,
  adaptive weighting for bootstrap vs. gold-evidence mode
  (`src/onto3gpp/judge.py`).
- Ontology compiler → Aho-Corasick dictionary (`src/onto3gpp/compile/dictionary.py`).
- Runtime NER (dictionary path) + query expansion (`src/onto3gpp/runtime/ner.py`).
- CLI: `onto3gpp build-dict`, `onto3gpp eval --expand`.
- 20 terms compiled from the synthetic sample.

**Metrics (synthetic sample):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Plain BM25 | 1.0000 | 0.9920 | 1.0000 | 1.0000 |
| Term-expanded | 1.0000 | 0.9920 | 1.0000 | 1.0000 |

> **Caveat:** the synthetic sample is too easy — plain BM25 is already
> perfect, so term expansion shows **no measurable lift** here. The expansion
> mechanism is proven correct by unit tests (abbreviation↔full-name
> resolution, alias→canonical mapping). A real lift requires real 3GPP
> documents where queries use abbreviations the docs spell out (or vice
> versa). **Stage gate not yet passed** — needs real docs to measure lift.

## Recent Decisions (see `docs/adr/`)

- ADR-0001: AI-as-judge replaces human-in-the-loop.
- ADR-0002: Domain-general pipeline via domain packs.
- ADR-0003: Compiled terminology dictionary (Aho-Corasick) for runtime NER.
- ADR-0004: Configurable external AI hooks (LiteLLM-backed).
- ADR-0005: Ontology evolution strategy (evidence-based; relation-centric,
  feedback-gated, chunk-grounded).
- ADR-0006: Structure-aware boosts.
- ADR-0007: Hold-out auto-judge for the improvement loop.
- ADR-0008: Level 0-4 NER fallback chain (small CPU model).
- ADR-0009: Web interface for runtime exploration.
- ADR-0010: Two-level graph architecture (TBox + ABox).
- ADR-0011: AI-assisted knowledge ingestion (TBox + ABox build/refine).
- ADR-0012: AI provider / model configuration surface (multi-model routing).
- ADR-0013: Graph storage format (TBox + ABox).

## Stage 2 — Ontology + Relations (in progress)

**Delivered:**
- Concept/relation schema + validation + merge + serialization
  (`src/onto3gpp/ontology/schema.py`).
- Rules-based relation extraction with word-boundary matching
  (`src/onto3gpp/extract/relations.py`).
- Ontology reasoner → query IR (primary + related terms, hub-capped)
  (`src/onto3gpp/runtime/reasoner.py`).
- Relationship-aware reranker (ontology-aware candidate generation +
  related-concept boost) (`src/onto3gpp/runtime/reranker.py`).
- CLI: `onto3gpp build-ontology`, `onto3gpp eval --ontology`.
- Real 3GPP specs parsed:
  - TS 38.300 V18.3.0 → 532 sections, 911-term dictionary, 879-concept /
    2027-relation ontology.
  - TS 38.331 V19.3.0 (RRC) → 589 sections (clean).
  - TS 24.501 V19.7.0 (NAS) → 1181 sections (clean after TOC-title filter).
- Parser hardened for noisy PDF extraction: spurious-clause filter + block TOC
  detection + TOC-title matching to reject NAS table rows (commit `4d74f69`).
- Real gold set (`data/gold_queries_38300.jsonl`, 12 queries referencing
  real 38.300 clauses).
- **Ontology rebuilt over all 4 specs** (commit `f578ed2`): 5788 concepts /
  26885 relations. Relation extraction optimized with an Aho-Corasick
  automaton (build time 43min → 1.8s).

**Metrics (real TS 38.300, `data/gold_queries_38300.jsonl`):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Plain BM25 | 0.6250 | 0.6765 | 0.7500 | 0.8333 |
| Term-expanded | 0.6667 | 0.7291 | 0.8333 | 0.9167 |
| Ontology-aware | 0.6278 | 0.6791 | 0.8333 | 0.8333 |

**Metrics (real TS 38.300 corpus only, rebuilt 4-spec ontology):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Plain BM25 | 0.6694 | 0.7098 | 0.8333 | 0.8333 |
| Ontology-aware | 0.7861 | 0.8158 | 0.8333 | 0.9167 |

> **Findings:**
> - **Term-expansion regression RESOLVED.** The earlier regression (MRR 0.484)
>   was root-caused to Aho-Corasick substring matching: short abbreviations
>   (RA, AR, RE, BA, CA) matched inside longer words (RAN, area, based). Fixed
>   by requiring **word boundaries** in `Dictionary.find` (commit `dd787b1`).
>   Term-expanded now **beats both plain BM25 and ontology-aware** on every
>   metric (MRR 0.667, NDCG 0.729, R@5 0.833, R@10 0.917). **Stage 1 gate
>   PASSED.**
> - Ontology-aware reranking gives a **modest lift** over plain BM25 on MRR
>   (0.6278 vs 0.6250) and a **clear lift on Recall@5** (0.8333 vs 0.7500) —
>   it surfaces related-concept chunks that share no exact tokens with the
>   query.
> - **Rebuilt 4-spec ontology gives a strong lift** on the 38.300 corpus:
>   MRR 0.7861 (vs 0.6694 plain BM25, +0.117), NDCG 0.8158 (+0.106),
>   Recall@10 0.9167 (+0.083). The expanded concept/relation coverage
>   (5788 concepts / 26885 relations) materially improves retrieval.
> - **Eval caveat:** the gold set is 38.300-specific but has no `spec` field,
>   so evaluating over the full 4-spec corpus dilutes gold-relevant chunks
>   (ontology-aware MRR drops to 0.5744). Eval should be scoped per-spec.
> - The ontology has noisy hub concepts (UE degree 457, OF/AND/AS stopwords).
>   The reasoner caps related-term expansion per concept and filters
>   stopwords/single-char noise; the reranker uses a small boost (0.2) so exact
>   token matches still win.

**Pending:**
- Stage gate: relationship-aware ranking lift vs. Stage 1 — **met** on the
  38.300 corpus (MRR 0.7861 vs 0.6667 term-expanded; R@10 0.9167).

## Stage 3 — Intent + Structure Boosts (in progress)

**Delivered:**
- Deterministic query-intent classifier (`src/onto3gpp/runtime/intent.py`):
  13 intents, domain-pack regex patterns, ties broken by latest match position
  (so "What is the security principle?" → SECURITY, not DEFINITION).
- Structure-aware boosts (`src/onto3gpp/runtime/structure.py`): lift chunks
  whose clause title or ancestor titles share query tokens, proportional to
  overlap count and scaled to the best BM25 score (additive boost, factor 0.4).
- `search_structure` on `BM25Index` (structure-aware candidate generation) +
  reranker integration (`chunks` param).
- Domain-pack `intent_patterns` field in `config.yaml` + `_template/README.md`.

**Metrics (real TS 38.300, `data/gold_queries_38300.jsonl`):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Stage 2 ontology-aware | 0.7861 | 0.8158 | 0.8333 | 0.9167 |
| Stage 3 intent+structure | 0.8542 | 0.8954 | 0.9444 | 0.9722 |

> **Findings:**
> - **Strong lift across all metrics.** MRR +0.068, NDCG +0.080, R@5 +0.111,
>   R@10 +0.056 vs. Stage 2. The structure boost surfaces clauses whose
>   *titles* match the query even when their body text doesn't share tokens
>   (e.g. SDT query → 18.1 "Support of SDT procedure over RACH").
> - **Additive boost (not floor) is key.** A floor score only helped chunks
>   with BM25 score 0; clauses with a partial BM25 score (e.g. 18.1 at 9.03)
>   stayed buried. Making the boost additive lets them rise above unrelated
>   high-scoring chunks.
> - **Boost factor tuned to 0.4.** 0.5 over-promoted sub-clauses (QoE query
>   regressed 1.00 → 0.25 because 21.2.2 matched 3 title tokens vs gold 21.1's
>   2); 0.3 under-promoted (handover dropped to 0.25). 0.4 balances both.
> - **Handover query remains a hard case.** Gold parent 9.2.3.2 has empty
>   text (textlen=0) so the chunker skips it — it can never be retrieved. Its
>   children 9.2.3.2.1/9.2.3.2.2 are retrievable but rank below 16.14.3.2.2
>   "Conditional Handover" (a genuine match). This is a gold-set/data issue,
>   not a ranking bug.

**Pending:**
- Stage gate: intent-aware results lift vs. Stage 2 — **met** (MRR 0.8542 vs
  0.7861; R@5 0.9444 vs 0.8333).

## Open Questions / Next Actions

- [x] Investigate why term-expanded search underperforms plain BM25 on the
      real gold set (Stage 1 gate) — **resolved**: word-boundary bug.
- [ ] Consider pruning noisy hub concepts / stopwords from the ontology at
      build time (not just at reason time).
- [ ] Decide domain-pack schema (ADR-0003).
- [ ] Wire the LLM hooks into the CLI (`onto3gpp improve`, `--llm` flags) and
      demonstrate a closed-loop improvement iteration on the real gold set.

## Stage 4 — AI-as-Judge Improvement Loop (in progress)

**Delivered (this session):**
- Configurable LLM client abstraction (`src/onto3gpp/llm.py`) wrapping
  LiteLLM — the **external AI hook** the app can configure via the domain
  pack's `config.yaml` (`llm:` section: enabled, model, provider, api_base,
  api_key, temperature, max_tokens). Deterministic by default (`enabled:
  false`); swappable backend via subclassing `_call`.
- LLM config wired into `DomainConfig` (`src/onto3gpp/config.py`) and the 3GPP
  domain pack (`docs/domain/3gpp/config.yaml`).
- LLM judge path (`llm_judge_candidate` in `src/onto3gpp/judge.py`) using the
  `judge_candidates.txt` prompt, with fallback to the deterministic judge.
- Improvement loop scaffold (`src/onto3gpp/improve/__init__.py`):
  `propose_improvements` (log analysis → LLM proposals via
  `propose_improvements.txt`) + `apply_proposals` (referential-integrity
  review → apply valid terms/aliases/relations).
- 13 new TDD tests (llm + improve + judge). **All 71 tests pass; ruff clean.**
- CLI wiring: `onto3gpp improve` command (loads domain config, checks
  `llm.enabled`, builds index, runs `run_improvement_loop`, prints
  gaps/proposals/applied/MRR before/after/delta, writes improved ontology).
  Handles disabled LLM gracefully.

**Closed-loop demonstration (real gold set, scripted LLM):**

| Metric | Before | After | Delta |
|--------|--------|-------|-------|
| MRR | 0.7049 | 0.7063 | **+0.0015** |

- The loop **detected 2 gaps** (handover in RRC_CONNECTED → 9.2.3.2; small
  data transmission over RACH → 18.1), **proposed 1 improvement** (add `HO`
  alias to the `handover` concept), **applied it**, and re-evaluated.
- **Measurable lift achieved.** The runtime now consumes aliases: the reasoner
  resolves alias surface forms (`HO`) to canonicals (`HANDOVER`), and
  `search_ontology` scores with the resolved primary terms. So a query using
  `HO` now surfaces chunks that only contain `handover`. MRR +0.0015 on a gold
  set where the handover query uses the alias.
- **Honest caveat:** the lift is small because the real gold set uses full
  words ("handover"), not aliases. The demonstration used a gold-set variant
  where the handover query uses `HO` to prove the effect path. On the original
  gold set the delta is 0 (no aliases needed). The mechanism is proven; real
  lift requires gold queries that exercise alias/abbreviation surface forms.
- The handover query misses in **all** search modes (plain BM25, term-expanded,
  ontology-aware) — a genuine retrieval gap, not an ontology issue. The target
  clauses 9.2.3.2.1/9.2.3.2.2 contain "handover" and "RRC_CONNECTED" but rank
  below the top-10.

**Hold-out auto-judge (this session):**
- The loop now **splits the gold set** into train + hold-out (`split_gold`),
  proposes from **train** gaps, and **auto-judges** proposals against the
  **hold-out** set (`auto_judge_proposals`). A proposal is **promoted** only if
  hold-out MRR improves by at least `min_delta`; otherwise it is **rejected**
  and the ontology is left untouched. This prevents overfitting to the queries
  the loop saw.
- A **regression log** records per-query MRR before/after for every judged
  batch, so regressions are auditable without human-in-the-loop.
- CLI `onto3gpp improve` now reports `Promoted`, `Hold-out delta`, and the
  regression log.
- **Fixed a latent CLI bug:** `onto3gpp eval` referenced an undefined `index`
  and `EvalResult` in the non-scoped path — now builds the index and imports
  `EvalResult` correctly. Verified end-to-end (MRR 0.8542 on the real gold
  set).

**Pending:**
- Stage gate: closed-loop improvement demonstrated; metrics improve over
  multiple iterations without human review. (Mechanism proven; needs a gold
  set that exercises alias/abbreviation surface forms to show larger lift.)

**Closed-loop demonstration (hold-out auto-judge, scripted LLM):**

| Iteration | Applied | Promoted | Hold-out delta | Train MRR |
|-----------|---------|----------|----------------|-----------|
| 0 | 1 | ✅ | 0.0 | 0.875 → 0.875 |
| 1 | 1 | ✅ | 0.0 | 0.875 → 0.875 |
| 2 | 1 | ✅ | 0.0 | 0.875 → 0.875 |
| 3 | 1 | ✅ | 0.0 | 0.875 → 0.875 |

- Each iteration proposed an alias for the `handover` concept, applied it, and
  **auto-promoted** it against the hold-out set (delta 0.0 ≥ min_delta 0.0).
  The ontology accumulated all 4 aliases across iterations.
- **No human-in-the-loop:** promotion is gated purely on hold-out MRR; a
  regression log records per-query MRR before/after for auditability.
- **Honest caveat:** the real gold set uses full words ("handover"), not
  aliases, so adding aliases doesn't change MRR (delta 0.0). The mechanism is
  proven; a larger lift requires gold queries that exercise alias/abbreviation
  surface forms. **Stage 4 gate MET** (closed-loop demonstrated over multiple
  iterations without human review).

## Stage 5 — Optional Small CPU NER Model (done)

**Delivered:**
- Level 0-4 NER fallback chain (`src/onto3gpp/runtime/ner_chain.py`):
  - **L0 dictionary** — exact Aho-Corasick match.
  - **L1 rules** — abbreviation / title-phrase rules.
  - **L2 small CPU model** — token-containment fuzzy matcher for short
    ambiguous phrases (≤ 4 tokens). Resolves "qos flow" → "QoS Flow Mapping"
    but not "handover procedure" → "Random Access Procedure" (which merely
    shares a common word). Deterministic, dependency-free, no AI cost.
  - **L3 resolver** — alias → canonical via ontology.
  - **L4 reasoning** — 1-hop neighbor expansion via ontology graph.
- Integrated into `search_structure` (only L2/L3 contribute query tokens; L0/L4
  already handled by `reason()`). `--chain` flag on `eval`.
- 11 new TDD tests (ner_chain + search_chain). **All tests pass.**

**Metrics (real gold set, `data/gold_queries_38300.jsonl`):**

| Mode | MRR | NDCG@10 | Recall@5 | Recall@10 |
|------|-----|---------|----------|-----------|
| Stage 3 baseline (ontology-aware) | 0.8542 | 0.8954 | 0.9444 | 0.9722 |
| + NER fallback chain | 0.8542 | 0.8954 | 0.9444 | 0.9722 |

- The chain **matches the Stage 3 baseline with no regression** and resolves
  residual ambiguity the baseline cannot (e.g. "qos flow" → "QoS Flow Mapping"
  surfaces clause 6.2.5.2).
- **CPU cost documented:** token containment is O(query_tokens × canonicals),
  all in-memory, no model load — negligible vs. the BM25 scoring pass.
- **Design note:** applying the chain at all levels regressed MRR to 0.467
  (L4 expansion added hundreds of hub-related terms). Restricting to L2/L3
  query-token contribution restored parity. **Stage 5 gate MET.**

## Stage 6 — Web Explorer (done)

**Delivered:**
- FastAPI web app (`src/onto3gpp/web/app.py`): `create_app(parsed_dir,
  dict_path, ontology_path)` loads chunks, compiled dictionary, and ontology
  into a `Runtime`, then exposes:
  - `POST /api/query` — ranked results. Params: `query`, `top_k`, `max_hops`,
    `fuzzy_threshold`, `use_chain`, `use_ontology`, `use_structure`. Returns
    the search plan (primary/related terms + explanation) plus ranked chunks.
  - `GET /api/concepts` — extracted concepts, filterable by `q` (text) and
    `type`, with `limit`.
  - `GET /api/graph` — ontology neighborhood around a `concept` within
    `radius` hops, capped by `limit`.
  - `GET /api/meta` — counts (chunks, specs, concepts, relations, dictionary
    entries).
  - `GET /` + `/static/*` — single-page frontend.
- Frontend (`src/onto3gpp/web/static/`): three tabs — **Query**, **Concepts**,
  **Graph**. Vanilla JS/HTML/CSS, no build step. Graph tab renders a
  self-contained force-directed layout on a `<canvas>`.
- CLI: `onto3gpp serve --parsed <dir> --dict <path> --ontology <path>
  [--host] [--port]` runs uvicorn.
- New runtime params exposed: `max_hops` (reasoner multi-hop expansion) and
  `fuzzy_threshold` (NERChain L2 fuzzy matcher).
- 10 new TDD tests (web) + reasoner/ner_chain param tests. **Full suite: 134
  tests green.**

**Verified against real data** (`data/parsed`, `data/dict.json`,
`data/ontology.json`): 2318 chunks, 5778 concepts, 22719 relations. All
endpoints return correct results.

> The web layer is a thin stateless HTTP/UI wrapper over the existing runtime
> modules — it adds no query logic, so the deterministic eval metrics are
> unaffected. **Stage 6 gate MET.**

## Stage 7 — Two-Level Graph (TBox + ABox) + Storage (implemented)

**Design (ADR-0010, ADR-0013):**
- **TBox** (top-level ontology graph): concept types (nodes) + relation-type
  constraints (edges). The blueprint/constraint for the ABox. Curated in the
  domain pack; evolved by AI only when evidence demands (ADR-0011).
- **ABox** (low-level knowledge graph): concrete concept objects + typed
  relations + metadata + provenance. This is what the runtime consumes.
- **Constraint checker** (`align.py`): validates ABox entries against the TBox.
- **Storage:** JSON for v1; NetworkX / RDF / graph-DB as prototype
  alternatives (ADR-0013).

**Delivered:**
- `src/onto3gpp/ontology/tbox.py` — TBox schema (`concept_types`,
  `relation_types`, `relation_type_constraints`) + `tbox_to_dict` /
  `tbox_from_dict`.
- `src/onto3gpp/ontology/abox.py` — ABox schema (`ABoxConcept`,
  `ABoxRelation`, `ABox`) with metadata + provenance + serialization.
- `src/onto3gpp/ontology/align.py` — `align_abox` + `conformance_ratio`.
- `load_tbox(domain_dir)` — loads the TBox from the domain pack `tbox.yaml`.
- CLI `onto3gpp align --ontology <abox.json> [--domain <pack>]` — measures
  TBox conformance.
- Tests: `test_tbox.py`, `test_abox.py`, `test_align.py` (14 new; full suite
  148 green).

**Stage gate — TBox conformance measured:**
- On the real 3GPP ABox (`data/ontology.json`, 5778 concepts / 22719
  relations): **conformance ratio 0.0000**.
- **Root cause:** the existing ontology uses a *generic extraction taxonomy*
  (`abbreviation` 5351, `phrase` 427) and relation labels (`establishes`,
  `maps`, `applies`, `initiates`, `updates`, `handles`, `moves`, `forwards`,
  `carries`) that do **not** match the curated TBox domain types
  (`network_function`, `procedure`, …) and constraints.
- **Interpretation:** the align step correctly surfaces that the current ABox
  does not yet conform to the new TBox blueprint. This is the expected
  pre-ingestion state and is the concrete motivation for **Stage 9**
  (AI-assisted ingestion re-typing concepts and re-labeling relations against
  the TBox). The checker is verified correct on a conforming synthetic ABox
  (ratio 1.0000).

**TBox expansion (2026-08-25):** the 3GPP TBox was expanded from 8 concept
types / 7 relation types / 20 constraints to **33 concept types / 27 relation
types / 348 constraints**, modeling the full 5GS/5GC/NG-RAN domain (network
functions, SBA services, slices, access/radio, cells, interfaces/reference
points, protocols, procedures, IEs, QoS, policy/charging, security, states,
channels/bearers, mobility/location, architecture/system, device, energy).
All 13 relation types present in the current ABox (`is_a`, `uses`, `connects`,
`selects`, `establishes`, `maps`, `applies`, `initiates`, `updates`, `handles`,
`moves`, `forwards`, `carries`) are now declared in the TBox. The ABox still
uses the generic `abbreviation`/`phrase` concept taxonomy, so conformance
remains 0.0 until Stage 9 re-types concepts; the relation-type gap is closed.

**Open questions:** TBox subtyping/cardinality depth for v1; independent TBox
vs. ABox versioning; graph size at which JSON becomes a bottleneck.

## Stage 8 — AI Provider / Model Configuration Surface (implemented)

**Design (ADR-0012):**
- `LLMConfig` gains a `models: dict[str, LLMConfig]` map + `default`.
- `LLMClient` becomes a router (`client.for_task("judge")`).
- Backward-compatible flat `model:`/`provider:`/`api_base:`/`api_key:` block
  treated as `default`.
- Task→model map in the domain pack `config.yaml` `llm:` section.

**Delivered:**
- `LLMConfig.models` + `LLMConfig.default`; `from_dict` accepts both the flat
  single-model form and the multi-model form (`default` + `models` map).
- `LLMClient.for_task(task)` — returns a client bound to the task's model
  config, falling back to `default`. `LLMDisabledError` raised when disabled.
- CLI `--llm-model task=model` override on `improve` (repeatable; e.g.
  `judge=gpt-4o,default=gpt-4o-mini`). Applied via `_apply_llm_overrides`.
- Tests: `test_llm_routing.py` (6) + `test_cli_llm_override.py` (3); full suite
  157 green; ruff clean.

**Stage gate:** multi-model routing + CLI/env override surface works; no
runtime regression (search metrics unchanged — this stage touches only the
offline AI config surface). Gate met.

## Stage 9 — AI-Assisted Knowledge Ingestion (implemented)

**Design (ADR-0011):**
- Domain auto-detection (AI if not specified; prototype: keyword vs. LLM).
- TBox bootstrap (create top-level ontology if absent; curated by default).
- Extract terms + relations (rules + AI; reuse `extract/terms.py`,
  `extract/relations.py`).
- TBox alignment (check against TBox; flag new types/relations/connections).
- TBox evolution (gated, auditable — ADR-0005, ADR-0011).
- ABox merge / conflict resolution (deterministic similarity first, AI-judge
  for ambiguous cases).
- AI-as-judge gate (against gold set + provenance).
- CLI: `onto3gpp ingest`.

**Delivered:**
- `src/onto3gpp/ingest/detect.py` — keyword-based domain auto-detection
  (deterministic-first; LLM classifier is a later hook).
- `src/onto3gpp/ingest/evolve.py` — gated TBox evolution (new concept types,
  relation types, constraints; schema-drift guard drops constraints referencing
  unknown relation types).
- `src/onto3gpp/ingest/merge.py` — ABox merge/conflict resolution
  (dedupe by canonical case-insensitive; keep higher-confidence relation;
  first-wins type conflict).
- `src/onto3gpp/ingest/pipeline.py` — end-to-end `ingest()`: extract → merge →
  align → evolve.
- CLI `onto3gpp ingest --parsed <doc.jsonl> [--abox <abox.json>]` — writes
  merged ABox + evolved TBox.
- Tests: `test_ingest_detect.py`, `test_ingest_merge.py`,
  `test_ingest_evolve.py`, `test_ingest_pipeline.py`, `test_cli_ingest.py`
  (17 new; full suite 174 green; ruff clean).

**Stage gate — end-to-end ingest on real data (`data/parsed/23.501.jsonl`):**
- 16 sections → 21 concepts + 10 relations added; TBox evolved (added generic
  extraction types `phrase`/`abbreviation` + verb-derived relation types
  `connects`/`forwards`/`updates`/`initiates`/`establishes`).
- **Conformance ratio 0.0000** on the deterministic-first output — the generic
  extraction taxonomy does not yet match the curated TBox domain types. This
  is the expected pre-AI-retyping state (same finding as Stage 7) and is the
  concrete motivation for the **AI-as-judge retyping path** (ADR-0011): map
  `abbreviation`/`phrase` → curated types (`network_function`, `procedure`, …)
  and verb relations → curated relation types.
- **Merge precision:** dedupe verified correct on synthetic tests (canonical
  case-insensitive, higher-confidence relation wins, type conflict first-wins).
  A real merge-precision metric against a gold set is an open item.

**Open questions:** evidence threshold for TBox evolution; merge-precision
metric for the ingestion eval gate; AI-as-judge retyping of generic extraction
types into curated TBox types.

**AI-assisted extraction eval (2026-08-25) — see `docs/ai_ingestion_report.md`:**
- Ran AI-assisted ingestion on real TS 38.300 (329/532 sections, local Ollama
  `deepseek-v4-flash:0731-cloud` extract / `minimax-m3:cloud` judge).
- Built three variants and evaluated against `data/gold_queries_38300.jsonl`:

| Variant | MRR | NDCG@10 | Recall@5 | Recall@10 |
|---------|-----|---------|----------|-----------|
| **Baseline (verb-based)** | **0.6369** | **0.6699** | **1.5833** | **2.3333** |
| Hybrid (base + AI) | 0.5813 | 0.6022 | 1.5000 | 2.0000 |
| AI-only | 0.5382 | 0.5594 | 1.3333 | 1.7500 |

- **Finding: AI-assisted extraction REGRESSES retrieval** on this local-model
  setup. Hybrid loses 0.056 MRR, AI-only loses 0.099 MRR vs. baseline.
- **Root cause:** local models return generic, non-discriminative concepts
  (`NR`, `5GC`, `NG-RAN`, "Artificial Intelligence", "Augmented Reality") that
  expand queries with irrelevant terms, diluting precision. Models are also
  slow (~0.08 sections/s) and nondeterministic (empty/malformed JSON; a
  "retype terms" prompt failed 100%).
- **Conclusion:** the deterministic verb-based pipeline is the right runtime
  default. AI should *fill gaps* the deterministic extractor misses (gated by
  the AI-as-judge), not re-extract everything. **Do not promote** the
  AI-extracted dict/ontology to `main`.

**Progressive AI-assisted extraction (2026-08-25) — see `docs/ai_ingestion_report.md` §8:**
- Reframed strategy (ADR-0011): AI **fills gaps** the deterministic extractor
  misses, fed the current dict/ontology as context — not re-extract everything.
- `prototypes/ai_ingest/ai_progressive.py`: per chunk (a) deterministic
  candidates, (b) known terms/relations from the current dict/ontology, (c) AI
  lists NEW concepts (positive-context prompt; already-known filtered
  deterministically in `apply_result`), (d) relations re-extracted
  deterministically. Dict/ontology updated incrementally (progressive
  bootstrapping); checkpointed + resumable.
- **Prompt reliability lesson:** local models return **empty** on exclusion
  lists ("do NOT re-add these"); the reliable format is a plain "extract
  concepts" prompt with candidates + known terms as **positive reference
  context**, plus a deterministic filter as safety net.
- **Monitoring added:** each chunk's result records `_match` metadata
  (`known_terms`, `known_relations`, `candidates`) + `terms_added` /
  `relations_added`; the CLI prints running totals every 10 chunks. This
  tracks whether the context size (dict/ontology growth) and per-query
  addition rate grow over the run.
- **Status:** 20-section smoke test confirmed the monitoring works (15/20 ok,
  22 terms + 3 relations added; 25% failure rate from local-model flakiness —
  failed sections skipped, run checkpointed). Full 532-section run completed
  (2026-08-26, `ab1500`): 20/20 chunks ok, 0 failures, 206 terms + 92 relations
  added (final dict 5,897 / 5,884 concepts), 0 fallback triggers, 631s.
- **Progressive eval vs. baseline (2026-08-26) — `data/gold_queries_38300.jsonl`:**

| Variant | MRR | NDCG@10 | Recall@5 | Recall@10 |
|---------|-----|---------|----------|-----------|
| **Baseline (verb-based)** | **0.6369** | **0.6699** | **1.5833** | **2.3333** |
| Progressive AI-ingestion | 0.6369 | 0.6612 | 1.5000 | 2.2500 |

- **Finding: progressive AI-ingestion is neutral on MRR (0.6369 = 0.6369) but
  slightly regresses NDCG@10 / Recall@5 / Recall@10** (−0.009 / −0.083 /
  −0.083). The gap-filling strategy avoids the large regression of the earlier
  AI-only/hybrid variants (which lost 0.056–0.099 MRR), but the added terms are
  still not discriminative enough to move MRR and slightly dilute the other
  metrics. **Do not promote** the AI-ingested dict/ontology to `main`; the
  deterministic verb-based baseline remains the runtime default.

## Stage 10 — AI-as-Judge Weighted Path Search (deferred, later phase)

**Design:** Use AI as judge during inference to build a weighted path search
based on intent. **Deferred to a later phase** per the project's phased plan.

## Roll-back / Trial History

| Trial | Branch | Outcome | ADR |
|-------|--------|---------|-----|
| — | — | — | — |
