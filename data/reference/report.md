# 38.300 Reference (manual, 3.1 + 3.2 only) — vs Baseline

**Generated:** `data/reference/dict_38300.json` + `ontology_38300.json` manually judged from `data/raw/38300/38300-i30.docx` Heading styles (no heuristic scrape).

**Method (verbatim, provenance-grounded):**
- **Clause 3.1 Abbreviations** — 231 abbreviations (style EW, `ABBR\tExpansion`), e.g. `5GC\t5G Core Network`, `FSA ID\tFrequency Selection Area Identity`, `AMF\tAccess and Mobility Management Function`. Canonical = abbr, alias = expansion.
- **Clause 3.2 Definitions** — 98 definitions (Normal paras `Term: definition`), e.g. `Conditional Handover (CHO): a handover procedure...`, `gNB: node providing...`, `BH RLC channel: an RLC channel...`. Canonical = term (parens stripped to alias).
- **Headings (clauses 4-9) — REMOVED.** Prior auto-extract added 144 heading titles as concepts (e.g. `Abbreviations and Definitions`, `General`, `Architecture`, `Access Control`, `Services and Functions`, single-word `HARQ`/`Capabilities`/`Handover`). Manual review: these are section scaffolding, not defined terms, so they pollute `canonical`. Dropped. A small hand-picked heading supplement can be re-added later only if a title is an unambiguous domain concept not already in 3.1/3.2 and maps cleanly to a TBox type (currently none — strict mode).

## Counts

| Artifact | Reference (3.1+3.2 only) | Baseline (`data/dict.json` + `ontology.json`) | Notes |
|----------|--------------------------|-----------------------------------------------|-------|
| Dict entries (surfaces) | 552 | 5815 | baseline heuristic caps scraping across 4 specs |
| Concepts | 329 (231 abbr + 98 def) | 5778 | ref is normative only |
| Relations | 18 | 22719 | ref curated clause-cited; baseline verb-heuristic |

## Why dict 552 > concepts 329

Each abbr contributes 2 surfaces (abbr + expansion alias) when expansion differs: 231 abbrs -> ~460 surfaces. 98 defs add ~90. Deduplicated = 552.

## Concept types (TBox-mapped, reference)

`concept:143, channel:40, network_function:29, architecture:27, qos:22, cell:21, connection:10, network_entity:8, mobility:5, protocol:5, interface:5, procedure:5, security:2, frequency_band:2, device:2, bearer:1, network_service:1, parameter:1` — generic `concept` fallback is 143/329 (43%), mostly abbrs with underspecified expansions.

## Dict coverage checks

- Example alias mapping (correct canonical): `5G Core Network -> 5GC`, `Access and Mobility Management Function -> AMF`, `Conditional Handover <- CHO` (alias stripped).
- Prior heading-as-canonical entries (e.g. `Abbreviations and Definitions -> Abbreviations and Definitions`, `Access Control -> Access Control`, `Architecture -> Architecture`) removed — they were not defined terms.

## Relations (reference — curated, clause-cited)

- 18 edges (`is_a`/`part_of`), each with `provenance.clause`, both endpoints in 3.1/3.2. Removed 11 edges whose target was a dropped heading (e.g. `NG Interface part_of Overall Architecture`). See `ontology_38300.json`.

## Comparison vs baseline (headline)

- **Baseline dict** 5815 vs ref 552: ~5263 more surfaces from heuristic scraping (4 specs, caps tokens like `A-1`, `A-CSI-RS`). Expect baseline higher recall but lower precision vs normative.
- **Overlap (case-sensitive exact, excluding headings):** canonical (entity = canonical ∪ aliases) 227/552 = 41.1%, surface (dict string) 246/552 = 44.6%. Same ballpark as before but now noise-free.
- **For evaluation** (`data/gold_queries_38300.jsonl`, 60 queries, `top_k=10`): plain BM25 MRR 0.5700, + ref dict 0.5803, + baseline dict 0.5971, + ref dict+onto rerank 0.6727 (vs baseline rerank 0.7185 — baseline's reranker benefits from more concepts but lower precision).
- **As regression gate (ADR-0011):** AI ingestion of new 38.300 revisions should not reduce canonical coverage of this 329-core; heading supplements require manual approval.

Previous auto build backed up to `data/reference/ontology_38300.pre-manual.json` / `dict_38300.pre-manual.json`. Build script: `scripts/build_38300_reference.py` (headings kept there for repro, manual prune applied post-hoc).
