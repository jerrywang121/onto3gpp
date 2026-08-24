"""CLI entry point for onto3gpp.

The CLI owns the whole offline pipeline + evaluation + recursive improvement.
Commands are added per roadmap stage (see docs/roadmap.md).
"""

from pathlib import Path

import click

from onto3gpp.parser import parse_file
from onto3gpp.search.bm25 import BM25Index
from onto3gpp.search.chunker import chunk_sections


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
    for path in sorted(spec_dir.glob("*.txt")):
        spec = path.stem
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
def eval(parsed: Path, gold: Path, top_k: int, expand: Path | None) -> None:
    """Build a BM25 index from parsed sections and evaluate against a gold set."""
    import json

    from onto3gpp.compile.dictionary import Dictionary
    from onto3gpp.evaluate import load_gold, evaluate
    from onto3gpp.search.chunker import Chunk

    chunks: list[Chunk] = []
    for path in sorted(parsed.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            chunks.append(
                Chunk(
                    spec=data["spec"],
                    release=data["release"],
                    clause=data["clause"],
                    title=data["title"],
                    text=data["text"],
                )
            )
    index = BM25Index.build(chunks)
    gold_queries = load_gold(gold)

    if expand is not None:
        dictionary = Dictionary.from_dict(json.loads(expand.read_text(encoding="utf-8")))
        result = evaluate(index, gold_queries, top_k=top_k, dictionary=dictionary)
        click.echo("Mode: term-expanded search")
    else:
        result = evaluate(index, gold_queries, top_k=top_k)
        click.echo("Mode: plain BM25")

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


if __name__ == "__main__":
    main()
