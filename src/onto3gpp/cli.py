"""CLI entry point for onto3gpp.

The CLI owns the whole offline pipeline + evaluation + recursive improvement.
Commands are added per roadmap stage (see docs/roadmap.md).
"""

from pathlib import Path

import click

from onto3gpp.parser import parse_docx, parse_file
from onto3gpp.search.bm25 import BM25Index


@click.group()
def main() -> None:
    """onto3gpp — ontology-guided RAG pipeline (AI offline, deterministic runtime)."""


@main.command()
def version() -> None:
    """Print the version."""
    from onto3gpp import __version__

    click.echo(f"onto3gpp {__version__}")


@main.command()
@click.option("--spec-dir", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--release", default="Rel-18", help="3GPP release tag")
@click.option("--out", type=click.Path(path_type=Path), default="data/parsed")
def parse(spec_dir: Path, release: str, out: Path) -> None:
    """Parse all .txt files in a spec dir into structured sections (JSONL)."""
    import json

    out.mkdir(parents=True, exist_ok=True)
    total = 0
    for path in sorted(spec_dir.glob("*.txt")) + sorted(spec_dir.glob("*.docx")):
        spec = path.stem
        if path.suffix == ".docx":
            sections = parse_docx(path, spec=spec, release=release)
        else:
            sections = parse_file(path, spec=spec, release=release)
        out_path = out / f"{spec}.jsonl"
        with out_path.open("w", encoding="utf-8") as f:
            for s in sections:
                f.write(json.dumps(s.__dict__) + "\n")
        total += len(sections)
        click.echo(f"  {path.name}: {len(sections)} sections")
    click.echo(f"Parsed {total} sections into {out}")


@main.command()
@click.option("--parsed", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--gold", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--top-k", default=10, show_default=True)
@click.option(
    "--expand",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a compiled dictionary (JSON) to enable term-expanded search.",
)
@click.option(
    "--ontology",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to an ontology (JSON) to enable relationship-aware reranking.",
)
@click.option(
    "--chain",
    is_flag=True,
    default=False,
    help="Use the Level 0-4 NER fallback chain for query expansion.",
)
@click.option("--max-chars", default=500, show_default=True, help="Max chunk length in characters.")
@click.option("--overlap", default=80, show_default=True, help="Chunk overlap in characters.")
def eval(
    parsed: Path,
    gold: Path,
    top_k: int,
    expand: Path | None,
    ontology: Path | None,
    chain: bool,
    max_chars: int,
    overlap: int,
) -> None:
    """Build a BM25 index from parsed sections and evaluate against a gold set."""
    import json

    from onto3gpp.compile.dictionary import Dictionary
    from onto3gpp.evaluate import EvalResult, evaluate, load_gold
    from onto3gpp.ontology.schema import ontology_from_dict
    from onto3gpp.search.chunker import Chunk, load_chunks

    chunks = load_chunks(parsed, max_chars=max_chars, overlap=overlap)
    gold_queries = load_gold(gold)

    dictionary = None
    if expand is not None:
        dictionary = Dictionary.from_dict(json.loads(expand.read_text(encoding="utf-8")))

    onto = None
    if ontology is not None:
        onto = ontology_from_dict(json.loads(ontology.read_text(encoding="utf-8")))

    # If gold queries carry a `spec`, evaluate each query against an index
    # built only from that spec's chunks. This avoids diluting gold-relevant
    # results with chunks from other specs in a multi-spec corpus.
    scoped = any(gq.spec for gq in gold_queries)
    if scoped:
        by_spec: dict[str, list[Chunk]] = {}
        for c in chunks:
            by_spec.setdefault(c.spec, []).append(c)
        results: list[EvalResult] = []
        for gq in gold_queries:
            spec_chunks = by_spec.get(gq.spec, chunks)
            spec_index = BM25Index.build(spec_chunks)
            results.append(
                evaluate(
                    spec_index,
                    [gq],
                    top_k=top_k,
                    dictionary=dictionary,
                    ontology=onto,
                    chain=chain,
                )
            )
        # aggregate per-query results into a single EvalResult
        n = len(results)
        result = EvalResult(
            mrr=sum(r.mrr for r in results) / n if n else 0.0,
            ndcg_at_10=sum(r.ndcg_at_10 for r in results) / n if n else 0.0,
            recall_at_5=sum(r.recall_at_5 for r in results) / n if n else 0.0,
            recall_at_10=sum(r.recall_at_10 for r in results) / n if n else 0.0,
            num_queries=n,
            per_query=[q for r in results for q in r.per_query],
        )
    else:
        index = BM25Index.build(chunks)
        result = evaluate(
            index,
            gold_queries,
            top_k=top_k,
            dictionary=dictionary,
            ontology=onto,
            chain=chain,
        )

    modes = []
    if chain:
        modes.append("NER fallback chain")
    if dictionary is not None:
        modes.append("term-expanded search")
    if onto is not None:
        modes.append("relationship-aware reranking")
    if not modes:
        modes.append("plain BM25")
    click.echo(f"Mode: {' + '.join(modes)}")

    click.echo(f"Queries: {result.num_queries}")
    click.echo(f"MRR:        {result.mrr:.4f}")
    click.echo(f"NDCG@10:    {result.ndcg_at_10:.4f}")
    click.echo(f"Recall@5:   {result.recall_at_5:.4f}")
    click.echo(f"Recall@10:  {result.recall_at_10:.4f}")


@main.command()
@click.option("--parsed", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), default="data/dict.json")
@click.option("--threshold", default=0.8, show_default=True)
def build_dict(parsed: Path, out: Path, threshold: float) -> None:
    """Extract + judge + compile a terminology dictionary from parsed sections."""
    import json

    from onto3gpp.compile.dictionary import build_dictionary
    from onto3gpp.extract.terms import extract_candidates
    from onto3gpp.judge import gate_candidates
    from onto3gpp.parser import Section

    sections: list[Section] = []
    for path in sorted(parsed.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            sections.append(
                Section(
                    spec=data["spec"],
                    release=data["release"],
                    clause=data["clause"],
                    title=data["title"],
                    text=data["text"],
                    parent_clause=data.get("parent_clause", ""),
                    metadata=data.get("metadata", {}),
                )
            )

    candidates = extract_candidates(sections)
    gated = gate_candidates(candidates, threshold=threshold)
    dictionary = build_dictionary(gated)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dictionary.to_dict(), indent=2), encoding="utf-8")
    click.echo(f"Candidates: {len(candidates)}")
    click.echo(f"Accepted:   {len(gated)}")
    click.echo(f"Entries:    {len(dictionary.entries)}")
    click.echo(f"Wrote dictionary to {out}")


@main.command()
@click.option("--parsed", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--dict", "dict_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), default="data/ontology.json")
def build_ontology(parsed: Path, dict_path: Path, out: Path) -> None:
    """Build an ontology (concepts + relations) from parsed sections + dictionary."""
    import json

    from onto3gpp.compile.dictionary import Dictionary
    from onto3gpp.extract.relations import extract_relations
    from onto3gpp.ontology.schema import (
        Concept,
        Ontology,
        ontology_to_dict,
        validate_ontology,
    )
    from onto3gpp.parser import Section

    dictionary = Dictionary.from_dict(json.loads(dict_path.read_text(encoding="utf-8")))

    sections: list[Section] = []
    for path in sorted(parsed.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            sections.append(
                Section(
                    spec=data["spec"],
                    release=data["release"],
                    clause=data["clause"],
                    title=data["title"],
                    text=data["text"],
                    parent_clause=data.get("parent_clause", ""),
                    metadata=data.get("metadata", {}),
                )
            )

    # Concepts from dictionary entries (dedup by canonical)
    concepts: dict[str, Concept] = {}
    for entry in dictionary.entries.values():
        cid = entry.canonical.lower().replace(" ", "_")
        if cid not in concepts:
            concepts[cid] = Concept(
                id=cid,
                canonical=entry.canonical,
                type=entry.type,
                aliases=[a for a in entry.aliases if a != entry.canonical],
            )

    onto = Ontology(concepts=list(concepts.values()))
    relations = extract_relations(sections, onto)
    onto.relations = relations

    errors = validate_ontology(onto)
    if errors:
        click.echo("Validation errors:")
        for e in errors[:20]:
            click.echo(f"  {e}")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ontology_to_dict(onto), indent=2), encoding="utf-8")
    click.echo(f"Concepts:  {len(onto.concepts)}")
    click.echo(f"Relations: {len(onto.relations)}")
    click.echo(f"Wrote ontology to {out}")


@main.command()
@click.option("--parsed", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--gold", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--ontology", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path), default="data/ontology.json")
@click.option("--domain", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--top-k", default=10, show_default=True)
@click.option("--max-chars", default=500, show_default=True, help="Max chunk length in characters.")
@click.option("--overlap", default=80, show_default=True, help="Chunk overlap in characters.")
def improve(parsed: Path, gold: Path, ontology: Path, out: Path, domain: Path | None, top_k: int, max_chars: int, overlap: int) -> None:
    """Run one closed-loop improvement iteration (AI-as-judge).

    Evaluates the ontology against the gold set, finds gaps, asks the LLM
    (configured in the domain pack's config.yaml) to propose improvements,
    applies valid ones, and re-evaluates. Writes the improved ontology to
    --out.
    """
    import json

    from onto3gpp.config import load_domain
    from onto3gpp.evaluate import load_gold
    from onto3gpp.improve import run_improvement_loop
    from onto3gpp.llm import LLMClient
    from onto3gpp.ontology.schema import ontology_from_dict
    from onto3gpp.search.chunker import load_chunks

    # Load domain pack (for LLM config + prompt templates).
    if domain is None:
        domain = Path("docs/domain/3gpp")
    cfg = load_domain(domain)

    if not cfg.llm.enabled:
        click.echo("LLM is disabled in the domain pack config.yaml (llm.enabled: false).")
        click.echo("Enable it to run the AI-as-judge improvement loop.")
        raise SystemExit(1)

    # Build the BM25 index from parsed sections.
    chunks = load_chunks(parsed, max_chars=max_chars, overlap=overlap)
    index = BM25Index.build(chunks)

    gold_queries = load_gold(gold)
    onto = ontology_from_dict(json.loads(ontology.read_text(encoding="utf-8")))
    llm = LLMClient(cfg.llm)

    result = run_improvement_loop(
        index,
        gold_queries,
        onto,
        llm,
        top_k=top_k,
        domain_dir=domain,
    )

    click.echo(f"Gaps (queries missing relevant clause in top-{min(top_k,5)}): {len(result.gaps)}")
    click.echo(f"Proposals: {len(result.proposals)}")
    click.echo(f"Applied:   {result.applied}")
    click.echo(f"Promoted:  {result.promoted}")
    click.echo(f"MRR before: {result.before_mrr:.4f}")
    click.echo(f"MRR after:  {result.after_mrr:.4f}")
    click.echo(f"Delta:      {result.after_mrr - result.before_mrr:+.4f}")
    if result.holdout_delta is not None:
        click.echo(f"Hold-out delta: {result.holdout_delta:+.4f}")

    out.parent.mkdir(parents=True, exist_ok=True)
    from onto3gpp.ontology.schema import ontology_to_dict

    out.write_text(json.dumps(ontology_to_dict(onto), indent=2), encoding="utf-8")
    click.echo(f"Wrote improved ontology to {out}")


@main.command()
@click.option(
    "--ontology",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to an ABox ontology (JSON) to validate against the TBox.",
)
@click.option(
    "--domain",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a domain pack directory (default: docs/domain/3gpp).",
)
def align(ontology: Path, domain: Path | None) -> None:
    """Validate an ABox ontology against the domain pack's TBox (Stage 7).

    Reports the TBox conformance ratio: the share of ABox relations that
    satisfy the TBox (known concept types, known relation types, and allowed
    (source_type, rel, target_type) edges).
    """
    import json

    from onto3gpp.config import load_domain
    from onto3gpp.ontology.align import align_abox, conformance_ratio
    from onto3gpp.ontology.schema import ontology_from_dict

    if domain is None:
        domain = Path("docs/domain/3gpp")
    cfg = load_domain(domain)
    tbox = cfg.tbox()

    onto = ontology_from_dict(json.loads(ontology.read_text(encoding="utf-8")))
    from onto3gpp.ontology.abox import ABox, ABoxConcept, ABoxRelation

    abox = ABox(
        concepts=[
            ABoxConcept(id=c.id, canonical=c.canonical, type=c.type, aliases=c.aliases)
            for c in onto.concepts
        ],
        relations=[
            ABoxRelation(
                source=r.source,
                rel=r.rel,
                target=r.target,
                weight=r.weight,
                confidence=r.confidence,
                provenance=r.provenance,
            )
            for r in onto.relations
        ],
    )

    result = align_abox(abox, tbox)
    ratio = conformance_ratio(result)
    click.echo(f"Domain: {cfg.domain}")
    click.echo(f"TBox concept types: {len(tbox.concept_types)}")
    click.echo(f"TBox relation types: {len(tbox.relation_types)}")
    click.echo(f"TBox constraints: {len(tbox.relation_type_constraints)}")
    click.echo(f"ABox concepts: {len(abox.concepts)}")
    click.echo(f"ABox relations: {result.total_relations}")
    click.echo(f"Conforming relations: {result.conforming_relations}")
    click.echo(f"Conformance ratio: {ratio:.4f}")
    if result.errors:
        click.echo(f"Errors ({len(result.errors)}):")
        for e in result.errors[:20]:
            click.echo(f"  - {e}")
        if len(result.errors) > 20:
            click.echo(f"  ... and {len(result.errors) - 20} more")


@main.command()
@click.option("--parsed", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--dict",
    "dict_path",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to a compiled dictionary (JSON) to enable NER chain + expansion.",
)
@click.option(
    "--ontology",
    type=click.Path(exists=True, path_type=Path),
    default=None,
    help="Path to an ontology (JSON) to enable relationship-aware search + graph.",
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8000, show_default=True)
@click.option("--max-chars", default=500, show_default=True, help="Max chunk length in characters.")
@click.option("--overlap", default=80, show_default=True, help="Chunk overlap in characters.")
def serve(
    parsed: Path,
    dict_path: Path | None,
    ontology: Path | None,
    host: str,
    port: int,
    max_chars: int,
    overlap: int,
) -> None:
    """Serve the web interface for exploring the runtime (query + ontology)."""
    import uvicorn

    from onto3gpp.web.app import create_app

    app = create_app(
        parsed,
        dict_path=dict_path,
        ontology_path=ontology,
        max_chars=max_chars,
        overlap=overlap,
    )
    click.echo(f"Serving onto3gpp explorer at http://{host}:{port}")
    click.echo(f"  parsed:   {parsed}")
    click.echo(f"  dict:     {dict_path or '(none)'}")
    click.echo(f"  ontology: {ontology or '(none)'}")
    click.echo(f"  chunk:    max_chars={max_chars}, overlap={overlap}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
