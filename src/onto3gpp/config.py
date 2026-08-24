"""Domain-pack loading and configuration.

The pipeline is domain-agnostic: it reads a domain pack (prompts + config)
from docs/domain/<domain>/ and never hard-codes domain terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class DomainConfig:
    """Configuration loaded from a domain pack's config.yaml."""

    domain: str
    concept_types: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    document_metadata: list[str] = field(default_factory=list)
    judge_threshold: float = 0.8

    @classmethod
    def from_yaml(cls, path: Path) -> "DomainConfig":
        """Load a DomainConfig from a config.yaml file."""
        data = yaml.safe_load(path.read_text())
        return cls(**data)


def load_domain(domain_dir: Path) -> DomainConfig:
    """Load a domain pack from a directory containing config.yaml."""
    config_path = domain_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml in domain pack: {domain_dir}")
    return DomainConfig.from_yaml(config_path)
