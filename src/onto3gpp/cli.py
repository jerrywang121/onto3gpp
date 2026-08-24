"""CLI entry point for onto3gpp.

The CLI owns the whole offline pipeline + evaluation + recursive improvement.
Commands are added per roadmap stage (see docs/roadmap.md).
"""

import click


@click.group()
def main() -> None:
    """onto3gpp — ontology-guided RAG pipeline (AI offline, deterministic runtime)."""


@main.command()
def version() -> None:
    """Print the version."""
    from onto3gpp import __version__

    click.echo(f"onto3gpp {__version__}")


if __name__ == "__main__":
    main()
