"""Prototype: ontology graph consolidation.

Question: the ontology keeps adding new terms and lacks the ability to merge
similar ones. How should we consolidate the graph?

This prototype applies a layered, deterministic-first consolidation to
``data/ontology.json`` and measures how many concepts collapse:

  Layer 1 — Normalization:  strip hyphens, case-fold, collapse whitespace,
                            sort tokens (word-order-insensitive).
  Layer 2 — Fuzzy merge:    reuse the Dice bigram ``fuzzy_similarity`` from
                            ``runtime/ner_chain.py`` to merge near-duplicates
                            above a threshold.
  Layer 3 — Abbr<->full:    link all-caps abbreviations to their full-form
                            phrase (promote full form, keep abbr as alias).

Results are written to ``prototypes/consolidation/results/`` so we have a
record to check back later (not /tmp).
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Allow running from repo root without install
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from onto3gpp.runtime.ner_chain import fuzzy_similarity  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY = ROOT / "data" / "ontology.json"
OUT_DIR = Path(__file__).resolve().parent / "results"


# ---------------------------------------------------------------------------
# Layer 1: normalization
# ---------------------------------------------------------------------------

def normalize(canonical: str) -> str:
    """Normalize a canonical to a merge key.

    - case-fold
    - strip hyphens -> spaces (E-UTRAN -> EUTRAN)
    - collapse whitespace
    - sort tokens (word-order-insensitive: "Broadcast MBS" == "MBS Broadcast")
    """
    s = canonical.lower()
    s = s.replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    tokens = s.split()
    return " ".join(sorted(tokens))


# ---------------------------------------------------------------------------
# Layer 2: fuzzy merge (Dice bigram)
# ---------------------------------------------------------------------------

def _is_prefix_suffix_variant(a: str, b: str) -> bool:
    """True if one canonical is a prefix/suffix variant of the other.

    In 3GPP these are usually semantically distinct (PLMN vs HPLMN, EMM-REGISTERED
    vs EMM-DEREGISTERED), so they must NOT be merged.
    """
    a = a.lower().replace("-", "")
    b = b.lower().replace("-", "")
    return a in b or b in a


def fuzzy_merge(concepts, threshold: float = 0.85):
    """Greedy merge of near-duplicate concepts by Dice similarity.

    Guards against prefix/suffix variants (semantically distinct in 3GPP).
    Returns (merged_concepts, groups, merged) where groups maps a surviving
    canonical to the list of canonicals merged into it.
    """
    survivors: list[dict] = []
    groups: dict[str, list[str]] = {}
    merged = 0
    for c in concepts:
        best = None
        best_score = 0.0
        for s in survivors:
            if _is_prefix_suffix_variant(c["canonical"], s["canonical"]):
                continue
            score = fuzzy_similarity(c["canonical"], s["canonical"])
            if score > best_score:
                best = s
                best_score = score
        if best is not None and best_score >= threshold:
            merged += 1
            groups.setdefault(best["canonical"], []).append(c["canonical"])
            # union aliases, keep higher confidence
            for a in c.get("aliases", []):
                if a not in best["aliases"]:
                    best["aliases"].append(a)
        else:
            survivors.append(dict(c))
    return survivors, groups, merged


# ---------------------------------------------------------------------------
# Layer 3: abbreviation <-> full-form linking
# ---------------------------------------------------------------------------

ABBR_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*$")


def is_abbr(canonical: str) -> bool:
    return bool(ABBR_RE.fullmatch(canonical))


def link_abbreviations(concepts):
    """Link all-caps abbreviations to full-form phrases.

    A full-form phrase is a concept whose tokens, when joined, contain the
    abbreviation as a subsequence of initials (e.g. "Session Management
    Function" -> SMF). Promote the full form as canonical; keep the abbr as
    an alias.
    """
    full_forms = [c for c in concepts if not is_abbr(c["canonical"])]
    abbrs = [c for c in concepts if is_abbr(c["canonical"])]

    def initials(phrase: str) -> str:
        return "".join(w[0] for w in re.sub(r"[^a-z ]", "", phrase.lower()).split())

    linked = 0
    unlinked: list[dict] = []
    for a in abbrs:
        abbr = a["canonical"].replace("-", "")
        matched = False
        for f in full_forms:
            if initials(f["canonical"]) == abbr.lower():
                if a["canonical"] not in f["aliases"]:
                    f["aliases"].append(a["canonical"])
                linked += 1
                matched = True
                break
        if not matched:
            unlinked.append(a)
    return full_forms + unlinked, linked


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    data = json.loads(ONTOLOGY.read_text())
    concepts = data["concepts"]
    relations = data["relations"]
    n0 = len(concepts)

    report: dict = {"input": str(ONTOLOGY), "n_concepts_initial": n0}

    # --- Layer 1: normalization ---
    by_norm: dict[str, list[dict]] = defaultdict(list)
    for c in concepts:
        by_norm[normalize(c["canonical"])].append(c)
    norm_groups = {k: v for k, v in by_norm.items() if len(v) > 1}
    report["layer1_normalize"] = {
        "groups": len(norm_groups),
        "concepts_collapsed": sum(len(v) - 1 for v in norm_groups.values()),
    }
    # survivors after layer 1: one representative per normalized key
    l1_survivors = []
    for k, group in by_norm.items():
        rep = max(group, key=lambda c: len(c.get("aliases", [])))
        for c in group:
            if c is not rep and c["canonical"] not in rep["aliases"]:
                rep["aliases"].append(c["canonical"])
        l1_survivors.append(rep)

    # --- Layer 2: fuzzy merge (DIAGNOSTIC ONLY — not applied) ---
    # Dice bigram similarity is too permissive for 3GPP: single-character
    # changes flip meaning (START/STOP, ACTIVE/INACTIVE, ACTIVATION/DEACTIVATION,
    # distinct change-request IDs C1-*/CP-*). Even at 0.95 it produces
    # dangerous merges. So we report it as analysis, not as a consolidation step.
    l2_survivors, fuzzy_groups, fuzzy_merged = fuzzy_merge(l1_survivors, threshold=0.95)
    report["layer2_fuzzy_diagnostic"] = {
        "threshold": 0.95,
        "merged": fuzzy_merged,
        "groups": len(fuzzy_groups),
        "note": "DIAGNOSTIC ONLY. Dice bigram is unsafe for 3GPP terms "
        "(START/STOP, ACTIVE/INACTIVE, distinct C1-*/CP-* IDs). Not applied.",
    }

    # --- Layer 3: abbreviation linking (SAFE — applied) ---
    l3_survivors, linked = link_abbreviations(l1_survivors)
    report["layer3_abbr"] = {
        "abbr_concepts_initial": sum(1 for c in concepts if is_abbr(c["canonical"])),
        "linked_to_full_form": linked,
    }

    report["n_concepts_final"] = len(l3_survivors)
    report["total_collapsed"] = n0 - len(l3_survivors)

    # --- write outputs ---
    (OUT_DIR / "report.json").write_text(json.dumps(report, indent=2))
    (OUT_DIR / "consolidated_concepts.json").write_text(
        json.dumps(l3_survivors, indent=2)
    )
    (OUT_DIR / "fuzzy_groups_diagnostic.json").write_text(
        json.dumps(fuzzy_groups, indent=2)
    )
    (OUT_DIR / "normalize_groups.json").write_text(
        json.dumps({k: [c["canonical"] for c in v] for k, v in norm_groups.items()}, indent=2)
    )

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
