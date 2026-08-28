"""Tests for embed block in domain pack config."""

from pathlib import Path

from onto3gpp.config import DomainConfig


def test_embed_config_defaults_to_hash(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text("domain: test\n")
    cfg = DomainConfig.from_yaml(p)
    assert cfg.embed.kind == "hash"
    assert cfg.embed.dim == 384
    assert cfg.embed.threshold == 0.25
    assert cfg.embed.top_k == 5


def test_embed_config_parses_api_and_ollama(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
domain: test
embed:
  kind: ollama
  api_base: http://localhost:11434
  model: embeddinggemma:300m
  dim: 768
  threshold: 0.3
  top_k: 3
"""
    )
    cfg = DomainConfig.from_yaml(p)
    assert cfg.embed.kind == "ollama"
    assert cfg.embed.api_base == "http://localhost:11434"
    assert cfg.embed.model == "embeddinggemma:300m"
    assert cfg.embed.dim == 768
    assert cfg.embed.threshold == 0.3
    assert cfg.embed.top_k == 3


def test_embed_config_parses_api_kind(tmp_path: Path):
    p = tmp_path / "config.yaml"
    p.write_text(
        """
domain: test
embed:
  kind: api
  api_base: https://api.openai.com/v1
  model: text-embedding-3-small
  dim: 1536
"""
    )
    cfg = DomainConfig.from_yaml(p)
    assert cfg.embed.kind == "api"
    assert cfg.embed.api_base == "https://api.openai.com/v1"
