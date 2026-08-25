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


def test_domain_pack_tbox() -> None:
    """The 3gpp domain pack should build a TBox with constraints."""
    domain_dir = Path(__file__).resolve().parents[1] / "docs" / "domain" / "3gpp"
    cfg = load_domain(domain_dir)
    tbox = cfg.tbox()
    assert tbox.is_known_concept_type("network_function")
    assert tbox.is_known_relation_type("selects")
    assert tbox.allows("network_function", "selects", "network_function")
    assert not tbox.allows("network_function", "selects", "procedure")
