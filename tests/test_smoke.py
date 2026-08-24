"""Smoke tests for the package skeleton."""

from pathlib import Path

from onto3gpp import __version__
from onto3gpp.config import load_domain


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_load_domain_pack() -> None:
    """The 3gpp domain pack should load without error."""
    domain_dir = Path(__file__).resolve().parents[1] / "docs" / "domain" / "3gpp"
    cfg = load_domain(domain_dir)
    assert cfg.domain == "3gpp"
    assert "network_function" in cfg.concept_types
    assert cfg.judge_threshold == 0.8
