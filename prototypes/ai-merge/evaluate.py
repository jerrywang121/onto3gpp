"""Lab harness: retrieval + merge decisions over curated pairs.

No extra deps. Run:  python evaluate.py   or   python evaluate.py --embed api
Uses HashEmbedder by default; --embed tfidf uses TfIdfEmbedder.
If data/reference/ontology_38300.json exists, its concepts seed the index;
otherwise falls back to the synthetic corpus below (so the harness always runs).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# allow `import embed` / `import merge` when run from repo root or prototype dir
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
# allow `from onto3gpp.llm import ...` inside merge.py when repo src is needed
_SRC = _HERE.parents[2] / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from embed import EmbeddingIndex, HashEmbedder, TfIdfEmbedder, get_embedder  # noqa: E402
from merge import MergeJudge, decide  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic corpus (fallback when reference ontology not present)
# These are representative of the 329-concept reference; they cover the
# hard negatives flagged in prototypes/consolidation.
# ---------------------------------------------------------------------------
SYNTHETIC_EXISTING: list[tuple[str, str, str]] = [
    # (id, canonical, type)
    ("ngap", "NGAP", "interface"),
    ("eutran", "E-UTRAN", "architecture"),
    ("nrdc", "NR-DC", "procedure"),
    ("sldrx", "SL-DRX", "procedure"),
    ("broadcast_mbs", "Broadcast MBS", "service"),
    ("pdu_active", "PDU SESSION ACTIVE", "state"),
    ("emm_registered", "EMM-REGISTERED", "state"),
    ("t3444", "T3444", "timer"),
    ("c1_174182", "C1-174182", "identifier"),
    ("dci_1_0", "DCI-1-0", "identifier"),
    ("plmn", "PLMN", "identifier"),
    ("hplmn", "HPLMN", "identifier"),
    ("start", "START", "procedure"),
    ("activation", "ACTIVATION", "procedure"),
    ("five_qi", "5QI", "identifier"),
    ("five_gc", "5GC", "architecture"),
    ("amf", "AMF", "network_function"),
    ("smf", "SMF", "network_function"),
    ("upf", "UPF", "network_function"),
    ("rrc_connected", "RRC_CONNECTED", "state"),
    ("rrc_idle", "RRC_IDLE", "state"),
    ("qos_flow", "QoS Flow", "concept"),
    ("fivegs", "5GS", "architecture"),
    ("mps", "MPS", "service"),
    ("mcptt", "MCPTT", "service"),
]

# (new_canonical, new_type, expected_decision, expected_target_id_or_None, note)
PAIRS: list[tuple[str, str, str, str | None, str]] = [
    # --- MERGE: lexical variants that SHOULD collapse (normalization-safe) ---
    ("NG-AP", "interface", "MERGE", "ngap", "hyphen variant"),
    ("EUTRAN", "architecture", "MERGE", "eutran", "hyphen stripped"),
    ("NRDC", "procedure", "MERGE", "nrdc", "hyphen stripped"),
    ("SL DRX", "procedure", "MERGE", "sldrx", "hyphen→space"),
    ("MBS Broadcast", "service", "MERGE", "broadcast_mbs", "token order"),
    ("qos flow", "concept", "MERGE", "qos_flow", "case variant"),
    ("5gc", "architecture", "MERGE", "five_gc", "case variant"),
    ("ngap", "interface", "MERGE", "ngap", "case variant lower"),
    # --- ADD: hard negatives that MUST stay distinct (Dice-unsafe) ---
    ("PDU SESSION INACTIVE", "state", "ADD", None, "ACTIVE vs INACTIVE (opp)"),
    ("EMM-DEREGISTERED", "state", "ADD", None, "REGISTERED vs DEREGISTERED (opp)"),
    ("T3445", "timer", "ADD", None, "timer off-by-one vs T3444"),
    ("C1-174183", "identifier", "ADD", None, "CR id off-by-one vs C1-174182"),
    ("DCI-0-1", "identifier", "ADD", None, "DCI format vs DCI-1-0"),
    ("STOP", "procedure", "ADD", None, "START vs STOP (opp)"),
    ("DEACTIVATION", "procedure", "ADD", None, "ACTIVATION vs DEACTIVATION (opp)"),
    # --- ADD: distinct concepts that must not be merged via surface similarity ---
    # These are already in the index — the correct label when querying the
    # same canonical is MERGE (they are the same concept). The negative we
    # actually want to test for 5QI/5GC-style confusion is cross-concept:
    ("RRC_INACTIVE", "state", "ADD", None, "third RRC state, distinct from CONNECTED/IDLE"),
    # a true ADD with no close neighbour
    ("S-NSSAI", "identifier", "ADD", None, "no close neighbour in index"),
    ("QFI", "identifier", "ADD", None, "no close neighbour in index"),
]

# For the two cases where the expected ADD actually has an exact match in the
# index if we query the same string, we need to ensure we test the right thing.
# The harness below excludes the "self" hit when the new term normalizes to
# an existing canonical — for ADD cases we want to confirm the judge says ADD
# even though retrieval surfaces a neighbour. That's the whole point of the
# hard-negative test (embedding brings the neighbour, judge must reject).


def build_index(embedder) -> tuple[EmbeddingIndex, dict[str, str], dict[str, str]]:
    # Prefer reference ontology if present — more realistic
    ref = _HERE.parents[2] / "data" / "reference" / "ontology_38300.json"
    items: list[tuple[str, str]] = []
    id_to_canonical: dict[str, str] = {}
    id_to_type: dict[str, str] = {}
    if ref.exists():
        try:
            data = json.loads(ref.read_text())
            for c in data.get("concepts", []):
                cid = c["id"]
                can = c["canonical"]
                typ = c.get("type", "concept")
                items.append((cid, can))
                id_to_canonical[cid] = can
                id_to_type[cid] = typ
        except Exception as e:
            print(f"[warn] failed to load {ref}: {e}, using synthetic", file=sys.stderr)
            items = []
    if not items:
        for cid, can, typ in SYNTHETIC_EXISTING:
            items.append((cid, can))
            id_to_canonical[cid] = can
            id_to_type[cid] = typ

    idx = EmbeddingIndex(dim=embedder.dim, embedder=embedder)
    idx.add_many(items)
    return idx, id_to_canonical, id_to_type


def _find_repo_root() -> Path:
    for p in [_HERE, *_HERE.parents]:
        if (p / "pyproject.toml").exists():
            return p
        if (p / "docs" / "domain" / "3gpp" / "config.yaml").exists():
            return p
    return _HERE.parents[2]


def _make_llm_judge() -> "MergeJudge | None":
    """Try to build a MergeJudge bound to the `merge` LLM task from domain config."""
    try:
        from onto3gpp.config import load_domain  # type: ignore
        from onto3gpp.llm import LLMClient  # type: ignore

        repo = _find_repo_root()
        domain_dir = repo / "docs" / "domain" / "3gpp"
        if not domain_dir.exists():
            # fallback: construct directly from config.yaml
            import yaml

            cfg_path = repo / "docs" / "domain" / "3gpp" / "config.yaml"
            data = yaml.safe_load(cfg_path.read_text())
            from onto3gpp.llm import LLMConfig as _LC

            base = _LC.from_dict(data.get("llm"))
            merge_cfg = base.models.get("merge", base.default) if base.models else base.default
            return MergeJudge(llm_client=LLMClient(merge_cfg))

        dc = load_domain(domain_dir)
        merge_cfg = dc.llm.models.get("merge", dc.llm.default) if dc.llm.models else dc.llm.default
        # dc.llm.enabled gates all tasks; if false, treat as disabled
        if not dc.llm.enabled:
            print("[warn] domain llm.enabled is false — AI judge disabled", file=sys.stderr)
            return None
        # Probe: ensure the merge task is not disabled
        if not merge_cfg.enabled and dc.llm.enabled:
            # from_dict sets per-task enabled = top-level enabled, so this is unlikely
            pass
        client = LLMClient(merge_cfg)
        # quick liveness probe (does not consume a judge call) — skip if offline
        probe_judge = MergeJudge(llm_client=client)
        if not probe_judge._llm_available:
            print("[warn] LLM judge reports unavailable (config enabled=false)", file=sys.stderr)
            return None
        return probe_judge
    except Exception as e:
        print(f"[warn] could not create LLM judge: {e}", file=sys.stderr)
        return None


def run_harness(embedder_kind: str = "hash", use_llm: bool = False) -> dict:
    if embedder_kind == "tfidf":
        # fit on a small corpus of existing + pair queries for slightly better IDF
        corpus = [c for _, c, _ in SYNTHETIC_EXISTING] + [p[0] for p in PAIRS]
        ref = _HERE.parents[2] / "data" / "reference" / "ontology_38300.json"
        if ref.exists():
            try:
                data = json.loads(ref.read_text())
                corpus = [c["canonical"] for c in data.get("concepts", [])][:500]
            except Exception:
                pass
        embedder = TfIdfEmbedder(dim=384, corpus=corpus)
    elif embedder_kind in ("api", "ollama"):
        if embedder_kind == "ollama":
            from embed import OllamaEmbedder  # noqa: F401

            try:
                embedder = OllamaEmbedder(api_base="http://localhost:11434", model="embeddinggemma:300m", dim=768)
                # probe liveness
                embedder.embed(["probe"])
            except Exception as e:
                print(f"[info] --embed ollama unavailable ({e}); falling back to hash", file=sys.stderr)
                embedder = HashEmbedder(dim=384)
        else:
            print("[info] --embed api requested but no api_base configured; using hash for offline run", file=sys.stderr)
            embedder = HashEmbedder(dim=384)
    else:
        embedder = HashEmbedder(dim=384)

    idx, id_to_canonical, id_to_type = build_index(embedder)
    judge: MergeJudge
    if use_llm:
        llm_judge = _make_llm_judge()
        if llm_judge is not None:
            judge = llm_judge
            print(f"[info] AI judge enabled (model={getattr(llm_judge.llm_client.config, 'model', '?')})", file=sys.stderr)
        else:
            print("[info] AI judge unavailable, falling back to deterministic", file=sys.stderr)
            judge = MergeJudge(llm_client=None)
    else:
        judge = MergeJudge(llm_client=None)  # deterministic fallback; LLM path when configured

    # actual timed loop: one embed+search per pair (no judge LLM)
    t_search = time.perf_counter()
    for new_can, *_ in PAIRS:
        idx.search_text(new_can, top_k=5, threshold=0.0)
    search_ms = (time.perf_counter() - t_search) / max(1, len(PAIRS)) * 1000

    results: list[dict] = []
    tp = fp = tn = fn = 0
    correct_target = 0
    merge_total = 0
    recall_at_5_hits = 0
    merge_cases = 0

    for new_can, new_type, expected, expected_target, note in PAIRS:
        dec = decide(
            new_can,
            new_type,
            idx,
            judge,
            top_k=5,
            threshold=0.25,
            id_to_canonical=id_to_canonical,
            id_to_type=id_to_type,
        )
        pred = dec.decision
        # F1 accounting (MERGE is positive)
        if expected == "MERGE":
            merge_total += 1
            merge_cases += 1
            if pred == "MERGE":
                tp += 1
                if dec.target == expected_target:
                    correct_target += 1
                # retrieval recall@5: was target in neighbours?
                if any(cid == expected_target for cid, _ in dec.neighbours):
                    recall_at_5_hits += 1
            else:
                fn += 1
        else:  # expected ADD
            if pred == "ADD":
                tn += 1
            else:
                fp += 1

        results.append(
            {
                "new": new_can,
                "expected": expected,
                "predicted": pred,
                "target": dec.target,
                "expected_target": expected_target,
                "note": note,
                "neighbours": [(cid, round(float(s), 3)) for cid, s in dec.neighbours[:3]],
                "ok": pred == expected and (expected != "MERGE" or dec.target == expected_target),
            }
        )

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    accuracy = (tp + tn) / len(PAIRS) if PAIRS else 0.0
    target_acc = correct_target / merge_total if merge_total else 0.0
    retrieval_recall = recall_at_5_hits / merge_cases if merge_cases else 0.0

    summary = {
        "embedder": embedder_kind,
        "dim": embedder.dim,
        "index_size": len(idx.ids),
        "pairs": len(PAIRS),
        "merge_cases": merge_cases,
        "add_cases": len(PAIRS) - merge_cases,
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "accuracy": round(accuracy, 3),
        "target_accuracy": round(target_acc, 3),
        "retrieval_recall@5": round(retrieval_recall, 3),
        "p50_search_ms_per_term": round(search_ms, 3),
        "used_llm": bool(getattr(judge, "_llm_available", False)),
        "llm_model": getattr(getattr(judge, "llm_client", None), "config", None) and getattr(judge.llm_client.config, "model", None),  # type: ignore
        "results": results,
    }
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--embed", choices=["hash", "tfidf", "api", "ollama"], default="hash")
    ap.add_argument("--llm", action="store_true", help="use AI judge (LLM) instead of deterministic fallback")
    ap.add_argument("--no-llm", dest="llm", action="store_false")
    ap.set_defaults(llm=False)
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    args = ap.parse_args()

    summary = run_harness(args.embed, use_llm=args.llm)

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    print(f"\n=== ai-merge prototype  embed={summary['embedder']}  dim={summary['dim']}  index={summary['index_size']} ===\n")
    print(f"Pairs: {summary['pairs']}  (MERGE {summary['merge_cases']}, ADD {summary['add_cases']})")
    print(f"Precision {summary['precision']}  Recall {summary['recall']}  F1 {summary['f1']}  Accuracy {summary['accuracy']}")
    print(f"Target accuracy (MERGE): {summary['target_accuracy']}   Retrieval recall@5: {summary['retrieval_recall@5']}")
    print(f"Search p50: {summary['p50_search_ms_per_term']} ms/term (CPU hash, no LLM)\n")
    print(f"{'NEW':<24} {'EXP':<6} {'PRED':<6} {'OK':<3} {'TARGET':<14} {'NEIGHBOURS (top3)'}")
    print("-" * 110)
    for r in summary["results"]:
        ok = "✓" if r["ok"] else "✗"
        neigh = ", ".join(f"{cid}:{s}" for cid, s in r["neighbours"])
        tgt = r["target"] or "-"
        print(f"{r['new']:<24} {r['expected']:<6} {r['predicted']:<6} {ok:<3} {tgt:<14} {neigh}  # {r['note']}")

    # Failure highlights
    fails = [r for r in summary["results"] if not r["ok"]]
    if fails:
        print(f"\nFailures ({len(fails)}):")
        for r in fails:
            print(f"  - {r['new']!r}: expected {r['expected']} {r['expected_target']}, got {r['predicted']} {r['target']}  ({r['note']})")
    else:
        print("\nAll pairs correct ✓")

    print(f"\nLLM gate: {'enabled' if summary['used_llm'] else 'disabled (deterministic fallback — normalized match)'}")
    print("Swap to API embedding: get_embedder({'kind':'api','api_base':'https://...','model':'text-embedding-3-small','api_key':'...'})")
    print("Swap to LLM judge:   MergeJudge(LLMClient(LLMConfig(enabled=True, model='...')))\n")

    # also write a JSON snapshot next to the report
    out = _HERE / "results.json"
    try:
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"Wrote {out}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
