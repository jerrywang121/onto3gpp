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
def eval(parsed: Path, gold: Path, top_k: int) -> None:
    """Build a BM25 index from parsed sections and evaluate against a gold set."""
    import json

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
    result = evaluate(index, gold_queries, top_k=top_k)
    click.echo(f"Queries: {result.num_queries}")
    click.echo(f"MRR:        {result.mrr:.4f}")
    click.echo(f"NDCG@10:    {result.ndcg_at_10:.4f}")
    click.echo(f"Recall@5:   {result.recall_at_5:.4f}")
    click.echo(f"Recall@10:  {result.recall_at_10:.4f}")


if __name__ == "__main__":
    main()
