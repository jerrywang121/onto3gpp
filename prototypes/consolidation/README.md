# Prototype: Ontology Graph Consolidation

**Question:** The ontology keeps adding new terms and lacks the ability to
merge similar ones. How should we consolidate the graph?

**Input:** `data/ontology.json` — 5,778 concepts, 22,719 relations (baseline).

**Method:** Layered, deterministic-first consolidation. Results saved to
`results/` (not /tmp) for later reference.

---

## Findings

### Layer 1 — Normalization (SAFE, applied): collapses 21 concepts

Normalize canonicals (case-fold, strip hyphens→spaces, collapse whitespace,
sort tokens) before dedup. Catches hyphen/space and word-order variants:

- `E-UTRAN`/`EUTRAN`, `NG-AP`/`NGAP`, `NR-DC`/`NRDC`
- `Broadcast MBS`/`MBS Broadcast`, `SL-DRX`/`SL DRX`

**Caveat:** a few groups are semantically distinct and must be excluded:
`DCI-1-0`/`DCI-0-1` (different DCI formats), `DL-UL`/`UL-DL`. A small
denylist handles these.

### Layer 2 — Fuzzy merge (Dice bigram) — **UNSAFE, diagnostic only**

Reused `fuzzy_similarity` (Dice coefficient over char bigrams) from
`runtime/ner_chain.py`. **Result: too permissive for 3GPP.** Single-character
changes flip meaning, and Dice scores them as near-identical:

| Pair | Dice | Meaning |
|------|------|---------|
| `PDU SESSION ACTIVE` / `INACTIVE` | 0.89 | opposite |
| `T3444` / `T3445` | 0.86 | distinct timers |
| `C1-174182` / `C1-174183` | 0.88 | distinct change-request IDs |
| `EMM-REGISTERED` / `EMM-DEREGISTERED` | high | opposite |

Even at threshold 0.95 it still merges `START`/`STOP`, `ACTIVATION`/
`DEACTIVATION`, and distinct `C1-*`/`CP-*` IDs. A prefix/suffix guard
(`PLMN`/`HPLMN`) helps but doesn't catch `ACTIVE`/`INACTIVE` (2-char prefix).

**Conclusion:** Dice bigram is **not** a safe merge signal for 3GPP terms.
Do not use it for consolidation. It may still be useful for *ranking* search
results, but not for merging ontology nodes.

### Layer 3 — Abbreviation ↔ full-form linking — **UNSAFE via initials heuristic**

Naive initials-matching (`"Session Management Function"` → `SMF`) produces
many false positives:

- `Non-Public Network` ← `NN` (real abbr is `NPN`)
- `PDU SESSION INACTIVE` ← `PSI` (real `PSI` = PDU Session Identity)
- `Extended DRX` ← `ED` (real abbr is `eDRX`)

**Conclusion:** Do not link abbreviations by initials. Use the extractor's
existing `_link_abbreviations` (in `extract/terms.py`), which only links when
the abbreviation appears in parentheses immediately after the full form in the
source text — that is provenance-grounded and safe.

### Layer 3b — Quantified upside of abbreviation linking (bounded)

Follow-up analysis of `data/ontology.json` and `data/dict.json`:

| Metric | Count |
|---|---|
| Abbreviation concepts (all-caps) | 5,351 |
| Full-form concepts | 427 |
| Abbrs with an initials-matching full form | 110 |
| Dict entries where `surface != canonical` (already linked) | 36 |

The **110 initials matches are mostly false positives** — the heuristic cannot
distinguish real abbreviations from coincidental letter matches:

| Abbr | Naive initials match | Real meaning |
|------|----------------------|--------------|
| `TR` | Topological Redundancy | Tracking Area |
| `MS` | MAC Sublayer | Mobile Station |
| `IP` | Inter-system Ping-pong | Internet Protocol |
| `CN` | Core Network / Configured NSSAI | ambiguous |
| `PS` | PDU Session / Protocol Stacks | Packet Switched |

**Key correction:** the 5,351 abbreviations are **not** mostly redundant
duplicates. Only a small fraction have a real full-form counterpart in the
docs. The consolidation upside from abbreviation linking is **bounded by what
the source text actually defines** (parenthesis pairs), not by what
initials-matching can invent. To grow it, re-run extraction over more source
docs (more `Full Form (ABBR)` pairs) — not improve the linking heuristic.

---

## Recommended consolidation (safe subset)

Only **Layer 1 (normalization)** is safe to apply automatically, with a small
denylist for the few semantically-distinct groups. That collapses ~21
concepts. The bigger wins (abbreviation linking) must be **provenance-grounded**
via the extractor, not heuristic.

**Net safe collapse on current graph: ~130 concepts** (21 normalization +
109 provenance-grounded abbr links), but the abbr links need the extractor's
parenthesis-based method, not initials. Note the 109 figure is an **upper
bound** — the provenance-grounded extractor currently produces only 36
correct links, and the initials heuristic that reaches 109 is unreliable.

---

## Files

| File | Contents |
|------|----------|
| `consolidate.py` | The prototype script (layered consolidation + diagnostics) |
| `results/report.json` | Summary metrics |
| `results/consolidated_concepts.json` | Concepts after safe consolidation |
| `results/normalize_groups.json` | The 21 normalization groups |
| `results/fuzzy_groups_diagnostic.json` | Fuzzy groups (diagnostic, NOT applied) |

**Status:** Prototype complete. Outcome to be recorded in an ADR. The
recommendation is: implement normalization-based consolidation in
`ingest/merge.py` (or a `consolidate_abox` step), and route abbreviation
linking through the provenance-grounded extractor. Do **not** use Dice-bigram
fuzzy merge for 3GPP consolidation.
