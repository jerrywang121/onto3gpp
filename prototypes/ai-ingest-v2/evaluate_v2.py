"""Lab + corpus evaluation for AI Ingest v2.

1) Lab harness: term 18-pair + relation 12-pair, P/R/F1, retrieval recall@k, judges deterministic by default.
2) Corpus smoke: optional --dict/--ontology vs baseline files; prints validation, retrieval (MRR/NDCG/Recall) on gold set.

Usage:
  .venv/bin/python prototypes/ai-ingest-v2/evaluate_v2.py                         # lab only (CPU, no LLM, deterministic)
  .venv/bin/python prototypes/ai-ingest-v2/evaluate_v2.py --dict /tmp/v2_dict.json --ontology /tmp/v2_ontology.json --gold data/gold_queries_38300.jsonl --parsed data/parsed/38300-i30.jsonl
  .venv/bin/python prototypes/ai-ingest-v2/evaluate_v2.py --llm --app-config config/app.yaml   # with LLM judges when configured
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parents[2] if _HERE.name == "ai-ingest-v2" else Path.cwd()
_SRC = _REPO / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from onto3gpp.app_config import load_app_config  # noqa: E402
from onto3gpp.compile.dictionary import Dictionary  # noqa: E402
from onto3gpp.embed import EmbeddingIndex, HashEmbedder, get_embedder  # noqa: E402
from onto3gpp.ingest.merge_judge import MergeJudge  # noqa: E402
from onto3gpp.llm import LLMClient  # noqa: E402
from onto3gpp.ontology.schema import Relation  # noqa: E402

# Reuse term synthetic + PAIRS from ai-merge prototype when available
_AI_MERGE_EVAL = _REPO / "prototypes" / "ai-merge" / "evaluate.py"
SYNTHETIC_EXISTING: list[tuple[str, str, str]] = [
    ("ngap", "NGAP", "interface"), ("eutran", "E-UTRAN", "architecture"),
    ("nrdc", "NR-DC", "procedure"), ("sldrx", "SL-DRX", "procedure"),
    ("broadcast_mbs", "Broadcast MBS", "service"), ("pdu_active", "PDU SESSION ACTIVE", "state"),
    ("emm_registered", "EMM-REGISTERED", "state"), ("t3444", "T3444", "timer"),
    ("c1_174182", "C1-174182", "identifier"), ("dci_1_0", "DCI-1-0", "identifier"),
    ("plmn", "PLMN", "identifier"), ("hplmn", "HPLMN", "identifier"),
    ("start", "START", "procedure"), ("activation", "ACTIVATION", "procedure"),
    ("five_qi", "5QI", "identifier"), ("five_gc", "5GC", "architecture"),
    ("amf", "AMF", "network_function"), ("smf", "SMF", "network_function"),
    ("upf", "UPF", "network_function"), ("rrc_connected", "RRC_CONNECTED", "state"),
    ("rrc_idle", "RRC_IDLE", "state"), ("qos_flow", "QoS Flow", "concept"),
    ("fivegs", "5GS", "architecture"), ("mps", "MPS", "service"), ("mcptt", "MCPTT", "service"),
]
TERM_PAIRS: list[tuple[str, str, str, str | None, str]] = [
    ("NG-AP", "interface", "MERGE", "ngap", "hyphen variant"),
    ("EUTRAN", "architecture", "MERGE", "eutran", "hyphen stripped"),
    ("NRDC", "procedure", "MERGE", "nrdc", "hyphen stripped"),
    ("SL DRX", "procedure", "MERGE", "sldrx", "hyphen→space"),
    ("MBS Broadcast", "service", "MERGE", "broadcast_mbs", "token order"),
    ("qos flow", "concept", "MERGE", "qos_flow", "case variant"),
    ("5gc", "architecture", "MERGE", "five_gc", "case variant"),
    ("ngap", "interface", "MERGE", "ngap", "case lower"),
    ("PDU SESSION INACTIVE", "state", "ADD", None, "ACTIVE vs INACTIVE"),
    ("EMM-DEREGISTERED", "state", "ADD", None, "REGISTERED vs DEREGISTERED"),
    ("T3445", "timer", "ADD", None, "timer off-by-one"),
    ("C1-174183", "identifier", "ADD", None, "CR off-by-one"),
    ("DCI-0-1", "identifier", "ADD", None, "DCI format vs DCI-1-0"),
    ("STOP", "procedure", "ADD", None, "START vs STOP"),
    ("DEACTIVATION", "procedure", "ADD", None, "ACTIVATION vs DEACTIVATION"),
    ("RRC_INACTIVE", "state", "ADD", None, "third RRC state"),
    ("S-NSSAI", "identifier", "ADD", None, "no close neighbour"),
    ("QFI", "identifier", "ADD", None, "no close neighbour"),
]

# Relation synthetic: distinct endpoints/types must not merge even if lexically close
REL_EXISTING: list[tuple[str, str, str]] = [
    ("amf", "uses", "smf"), ("smf", "uses", "upf"), ("amf", "connects", "gNB"),
    ("gNB", "carries", "QoS Flow"), ("SMF", "handles", "PDU Session"),
]
# (new_source, new_rel, new_target, expected, expected_target_id or None, note)
REL_PAIRS: list[tuple[str, str, str, str, str | None, str]] = [
    ("amf", "uses", "smf", "MERGE", "amf|uses|smf", "exact triple"),
    ("AMF", "uses", "SMF", "MERGE", "amf|uses|smf", "case variant endpoints"),
    ("amf", "USEs", "smf", "MERGE", "amf|uses|smf", "case variant rel"),
    ("smf", "uses", "amf", "ADD", None, "reversed direction distinct"),
    ("amf", "connects", "smf", "ADD", None, "different relation type"),
    ("amf", "uses", "upf", "ADD", None, "different target"),
    ("upf", "uses", "smf", "ADD", None, "reversed + different source"),
    ("SMF", "handles", "PDU Session", "MERGE", "SMF|handles|PDU Session", "exact with space"),
    ("smf", "handles", "pdu session", "MERGE", "SMF|handles|PDU Session", "case variant with space"),
    ("gNB", "carries", "qos flow", "MERGE", "gNB|carries|QoS Flow", "case variant target"),
    ("amf", "carries", "QoS Flow", "ADD", None, "different source+rel"),
    ("gNB", "uses", "QoS Flow", "ADD", None, "different rel"),
]


def _build_term_index(embedder, pairs_exist: list[tuple[str,str,str]]) -> tuple[EmbeddingIndex, dict, dict]:
    idx = EmbeddingIndex(dim=embedder.dim, embedder=embedder)
    id_to_can = {}
    id_to_type = {}
    for cid, can, typ in pairs_exist:
        id_to_can[cid] = can
        id_to_type[cid] = typ
    idx.add_many([(cid, can) for cid, can, _ in pairs_exist])
    return idx, id_to_can, id_to_type


def _build_rel_index(embedder, rels: list[tuple[str,str,str]]) -> EmbeddingIndex:
    idx = EmbeddingIndex(dim=embedder.dim, embedder=embedder)
    items = [(f"{s}|{r}|{t}", f"{s} {r} {t}") for s, r, t in rels]
    idx.add_many(items)
    return idx


def run_term_harness(embedder, judge: MergeJudge, threshold: float = 0.25, top_k: int = 5) -> dict:
    from onto3gpp.ingest.merge_judge import decide as term_decide  # type: ignore
    idx, id_to_can, id_to_type = _build_term_index(embedder, SYNTHETIC_EXISTING)
    t0 = time.perf_counter()
    for new_can, *_ in TERM_PAIRS:
        idx.search_text(new_can, top_k=top_k, threshold=0.0)
    p50 = (time.perf_counter() - t0) / max(1, len(TERM_PAIRS)) * 1000
    tp = fp = tn = fn = 0
    correct_target = 0
    merge_total = recall_hits = 0
    results = []
    for new_can, new_type, expected, exp_tgt, note in TERM_PAIRS:
        dec = term_decide(new_can, new_type, idx, judge, top_k=top_k, threshold=threshold,
                          id_to_canonical=id_to_can, id_to_type=id_to_type)
        pred = dec.decision
        ok = pred == expected and (expected != "MERGE" or dec.target == exp_tgt)
        if expected == "MERGE":
            merge_total += 1
            if pred == "MERGE":
                tp += 1
                if dec.target == exp_tgt:
                    correct_target += 1
                if any(cid == exp_tgt for cid, _ in dec.neighbours):
                    recall_hits += 1
            else:
                fn += 1
        else:
            tn += 1 if pred == "ADD" else 0
            fp += 1 if pred != "ADD" else 0
        results.append({"new": new_can, "expected": expected, "predicted": pred, "target": dec.target,
                        "expected_target": exp_tgt, "ok": ok, "note": note,
                        "neighbours": [(cid, round(float(s), 3)) for cid, s in dec.neighbours[:3]]})
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2*prec*rec/(prec+rec) if (prec+rec) else 0.0
    acc = (tp+tn)/len(TERM_PAIRS) if TERM_PAIRS else 0.0
    return {"kind": "term", "pairs": len(TERM_PAIRS), "merge_cases": merge_total, "add_cases": len(TERM_PAIRS)-merge_total,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": round(prec,3), "recall": round(rec,3), "f1": round(f1,3),
            "accuracy": round(acc,3), "target_accuracy": round(correct_target/merge_total,3) if merge_total else 0,
            "retrieval_recall@5": round(recall_hits/merge_total,3) if merge_total else 0,
            "p50_ms": round(p50,3), "used_llm": bool(getattr(judge, "_llm_available", False)), "results": results}


def run_rel_harness(embedder, rel_judge, threshold: float = 0.25, top_k: int = 5) -> dict:
    rel_idx = _build_rel_index(embedder, REL_EXISTING)
    # neighbours_for_relations + RelMergeJudge logic inline
    import importlib.util as _ilu, pathlib as _pl
    spec = _ilu.spec_from_file_location("ingest_v2_mod", str(_HERE / "ingest_v2.py"))
    mod = _ilu.module_from_spec(spec)  # type: ignore
    spec.loader.exec_module(mod)  # type: ignore  # noqa: E402
    neighbours_for_relations = mod.neighbours_for_relations  # type: ignore
    tp = fp = tn = fn = 0
    correct_target = 0
    merge_total = recall_hits = 0
    results = []
    t0 = time.perf_counter()
    for s, r, t, *_ in REL_PAIRS:
        rel_idx.search_text(f"{s} {r} {t}", top_k=top_k, threshold=0.0)
    p50 = (time.perf_counter() - t0) / max(1, len(REL_PAIRS)) * 1000
    for s, r, t, expected, exp_tgt, note in REL_PAIRS:
        rel_obj = Relation(source=s, rel=r, target=t)
        neigh_map = neighbours_for_relations([rel_obj], rel_idx, threshold=threshold, top_k=top_k)
        neigh = neigh_map.get((s,r,t), [])
        res = rel_judge.judge(rel_obj, neigh)
        pred = res.get("decision", "ADD")
        ok = pred == expected and (expected != "MERGE" or res.get("target") == exp_tgt)
        if expected == "MERGE":
            merge_total += 1
            if pred == "MERGE":
                tp += 1
                if res.get("target") == exp_tgt:
                    correct_target += 1
                if any(nb.get("id") == exp_tgt for nb in neigh):
                    recall_hits += 1
            else:
                fn += 1
        else:
            tn += 1 if pred == "ADD" else 0
            fp += 1 if pred != "ADD" else 0
        results.append({"new": f"{s} --{r}--> {t}", "expected": expected, "predicted": pred, "target": res.get("target"),
                        "expected_target": exp_tgt, "ok": ok, "note": note,
                        "neighbours": [(nb.get("id"), round(float(nb.get("cosine",0)),3)) for nb in neigh[:3]]})
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2*prec*rec/(prec+rec) if (prec+rec) else 0.0
    acc = (tp+tn)/len(REL_PAIRS) if REL_PAIRS else 0.0
    return {"kind": "relation", "pairs": len(REL_PAIRS), "merge_cases": merge_total, "add_cases": len(REL_PAIRS)-merge_total,
            "tp": tp, "fp": fp, "tn": tn, "fn": fn, "precision": round(prec,3), "recall": round(rec,3), "f1": round(f1,3),
            "accuracy": round(acc,3), "target_accuracy": round(correct_target/merge_total,3) if merge_total else 0,
            "retrieval_recall@5": round(recall_hits/merge_total,3) if merge_total else 0,
            "p50_ms": round(p50,3), "used_llm": bool(getattr(rel_judge, "_llm_available", False)), "results": results}


def corpus_eval(dict_path: Path, onto_path: Path, gold_path: Path, parsed_path: Path, top_k: int = 10) -> dict | None:
    if not (dict_path.exists() and onto_path.exists() and gold_path.exists() and parsed_path.exists()):
        return None
    import json as _json
    from onto3gpp.compile.dictionary import Dictionary as _Dict
    from onto3gpp.evaluate import evaluate as _eval, load_gold as _load_gold
    from onto3gpp.ontology.schema import ontology_from_dict as _ofd
    from onto3gpp.search.bm25 import BM25Index as _BM25
    from onto3gpp.search.chunker import load_chunks as _lc
    dictionary = _Dict.from_dict(_json.loads(dict_path.read_text(encoding="utf-8")))
    onto = _ofd(_json.loads(onto_path.read_text(encoding="utf-8")))
    errors = []
    try:
        from onto3gpp.ontology.schema import validate_ontology as _val
        errors = _val(onto)
    except Exception:
        pass
    # load_chunks expects a directory; also handle single-file parsed
    from onto3gpp.search.chunker import chunk_sections as _cs  # noqa: E402
    from onto3gpp.parser import Section as _Sec  # noqa: E402
    if parsed_path.is_file():
        _sections = []
        for _line in parsed_path.read_text(encoding="utf-8").splitlines():
            if not _line.strip():
                continue
            _d = json.loads(_line)
            _sections.append(_Sec(spec=_d["spec"], release=_d["release"], clause=_d["clause"], title=_d["title"], text=_d["text"], parent_clause=_d.get("parent_clause",""), metadata=_d.get("metadata",{})))
        chunks = _cs(_sections, max_chars=500, overlap=80)
    else:
        chunks = _lc(parsed_path, max_chars=500, overlap=80)
    gold = _load_gold(gold_path)
    # scope per spec when gold carries spec (same as cli eval)
    from onto3gpp.search.chunker import Chunk as _Chunk
    scoped = any(gq.spec for gq in gold)
    if scoped:
        by_spec: dict[str, list] = {}
        for c in chunks:
            by_spec.setdefault(c.spec, []).append(c)
        from onto3gpp.evaluate import EvalResult as _ER
        results = []
        for gq in gold:
            spec_chunks = by_spec.get(gq.spec, chunks) or chunks
            if not spec_chunks:
                # no chunks for spec -> skip (counts as 0)
                from onto3gpp.evaluate import EvalResult as _ER2
                results.append(_ER2(mrr=0, ndcg_at_10=0, recall_at_5=0, recall_at_10=0, num_queries=1, num_retrieved=0))
                continue
            idx = _BM25.build(spec_chunks)
            results.append(_eval(idx, [gq], top_k=top_k, dictionary=dictionary, ontology=onto))
        n = len(results)
        mrr = sum(r.mrr for r in results)/n if n else 0
        ndcg = sum(r.ndcg_at_10 for r in results)/n if n else 0
        r5 = sum(r.recall_at_5 for r in results)/n if n else 0
        r10 = sum(r.recall_at_10 for r in results)/n if n else 0
    else:
        if not chunks:
            mrr = ndcg = r5 = r10 = 0.0
        else:
            idx = _BM25.build(chunks)
            res = _eval(idx, gold, top_k=top_k, dictionary=dictionary, ontology=onto)
            mrr, ndcg, r5, r10 = res.mrr, res.ndcg_at_10, res.recall_at_5, res.recall_at_10
    return {"dict_entries": len(dictionary.entries), "concepts": len(onto.concepts), "relations": len(onto.relations),
            "validation_errors": len(errors), "mrr": round(mrr,4), "ndcg@10": round(ndcg,4), "recall@5": round(r5,4), "recall@10": round(r10,4),
            "num_queries": len(gold), "num_chunks": len(chunks)}


def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate AI Ingest v2 (lab + optional corpus)")
    ap.add_argument("--app-config", default=None)
    ap.add_argument("--llm", action="store_true", help="enable LLM judges when app llm.enabled")
    ap.add_argument("--dict", dest="dict_path", default=None)
    ap.add_argument("--ontology", dest="onto_path", default=None)
    ap.add_argument("--gold", default=None, help="gold jsonl for corpus retrieval eval")
    ap.add_argument("--parsed", default=None, help="parsed jsonl for chunk build in corpus eval")
    ap.add_argument("--threshold", type=float, default=0.25)
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    app = load_app_config(Path(args.app_config) if args.app_config else None)
    embed_cfg = {"kind": getattr(app.embed, "kind", "hash"), "dim": getattr(app.embed, "dim", 384),
                 "threshold": getattr(app.embed, "threshold", 0.25), "top_k": getattr(app.embed, "top_k", 5)}
    for k in ("api_base", "model", "api_key", "api_key_env"):
        v = getattr(app.embed, k, None)
        if v is not None:
            embed_cfg[k] = v
    threshold = args.threshold
    top_k = args.top_k
    embedder = get_embedder(embed_cfg)

    # Judges
    if args.llm and app.llm.enabled:
        def _c(task: str):
            cfg = app.llm.models.get(task, app.llm.default) if app.llm.models else app.llm.default
            return LLMClient(cfg)
        merge_judge = MergeJudge(llm_client=_c("merge"))
        # rel judge shares merge client
        import importlib.util as _ilu2
        spec2 = _ilu2.spec_from_file_location("ingest_v2_mod2", str(_HERE / "ingest_v2.py"))
        mod2 = _ilu2.module_from_spec(spec2)  # type: ignore
        spec2.loader.exec_module(mod2)  # type: ignore
        RelMergeJudge = mod2.RelMergeJudge  # type: ignore
        rel_judge = RelMergeJudge(llm_client=_c("merge"))
        print(f"[info] LLM judges enabled merge={getattr(_c('merge').config, 'model', '?')} llm_available={merge_judge._llm_available}", file=sys.stderr)
    else:
        merge_judge = MergeJudge(llm_client=None)
        import importlib.util as _ilu3
        spec3 = _ilu3.spec_from_file_location("ingest_v2_mod3", str(_HERE / "ingest_v2.py"))
        mod3 = _ilu3.module_from_spec(spec3)  # type: ignore
        spec3.loader.exec_module(mod3)  # type: ignore
        RelMergeJudge = mod3.RelMergeJudge  # type: ignore
        rel_judge = RelMergeJudge(llm_client=None)
        print("[info] LLM judges disabled (deterministic fallback)", file=sys.stderr)

    term_summary = run_term_harness(embedder, merge_judge, threshold=threshold, top_k=top_k)
    rel_summary = run_rel_harness(embedder, rel_judge, threshold=threshold, top_k=top_k)

    corpus = None
    if args.dict_path and args.onto_path:
        dp = Path(args.dict_path); op = Path(args.onto_path)
        gp = Path(args.gold) if args.gold else _REPO / "data" / "gold_queries_38300.jsonl"
        pp = Path(args.parsed) if args.parsed else _REPO / "data" / "parsed" / "38300-i30.jsonl"
        corpus = corpus_eval(dp, op, gp, pp)

    summary = {"embedder": embed_cfg.get("kind"), "dim": embedder.dim, "threshold": threshold, "top_k": top_k,
               "term": term_summary, "relation": rel_summary, "corpus": corpus}

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return

    def _print_block(s: dict) -> None:
        print(f"\n=== {s['kind']}  pairs={s['pairs']} (MERGE {s['merge_cases']}, ADD {s['add_cases']}) ===")
        print(f"Precision {s['precision']}  Recall {s['recall']}  F1 {s['f1']}  Accuracy {s['accuracy']}")
        print(f"Target-acc {s['target_accuracy']}  Retrieval recall@5 {s['retrieval_recall@5']}  p50 {s['p50_ms']} ms/term  llm={s['used_llm']}")
        fails = [r for r in s["results"] if not r["ok"]]
        if fails:
            print(f"Failures ({len(fails)}):")
            for r in fails:
                print(f"  - {r['new']!r}: exp {r['expected']} {r['expected_target']}, got {r['predicted']} {r['target']}  ({r['note']})  neigh={r['neighbours'][:2]}")
        else:
            print("All pairs correct")

    print(f"\n=== AI Ingest v2 evaluate  embed={embed_cfg.get('kind')} dim={embedder.dim} threshold={threshold} top_k={top_k} ===")
    _print_block(term_summary)
    _print_block(rel_summary)
    if corpus is not None:
        print(f"\n=== Corpus smoke  dict={corpus['dict_entries']} concepts={corpus['concepts']} rels={corpus['relations']} ===")
        print(f"Validation errors: {corpus['validation_errors']}")
        print(f"Retrieval: MRR {corpus['mrr']} NDCG@10 {corpus['ndcg@10']} Recall@5 {corpus['recall@5']} Recall@10 {corpus['recall@10']}  queries={corpus['num_queries']} chunks={corpus['num_chunks']}")
    else:
        print("\n(corpus smoke skipped — pass --dict/--ontology/--gold/--parsed to evaluate retrieval)")


if __name__ == "__main__":
    main()
