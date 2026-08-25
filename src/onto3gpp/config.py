"""Domain-pack loading and configuration.

The pipeline is domain-agnostic: it reads a domain pack (prompts + config)
from docs/domain/<domain>/ and never hard-codes domain terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from onto3gpp.llm import LLMConfig
from onto3gpp.ontology.tbox import TBox


@dataclass
class DomainConfig:
    """Configuration loaded from a domain pack's config.yaml."""

    domain: str
    concept_types: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    relation_type_constraints: list[dict] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    intent_patterns: dict[str, list[str]] = field(default_factory=dict)
    document_metadata: list[str] = field(default_factory=list)
    judge_threshold: float = 0.8
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> DomainConfig:
        """Load a DomainConfig from a config.yaml file."""
        data = yaml.safe_load(path.read_text())
        llm = LLMConfig.from_dict(data.pop("llm", None))
        return cls(**data, llm=llm)

    def tbox(self) -> TBox:
        """Build the TBox (top-level ontology graph) from this config."""
        from onto3gpp.ontology.tbox import RelationTypeConstraint

        constraints = [
            RelationTypeConstraint(
                source_type=c["source_type"],
                rel=c["rel"],
                target_type=c["target_type"],
            )
            for c in self.relation_type_constraints
        ]
        return TBox(
            concept_types=list(self.concept_types),
            relation_types=list(self.relation_types),
            relation_type_constraints=constraints,
        )


def load_domain(domain_dir: Path) -> DomainConfig:
    """Load a domain pack from a directory containing config.yaml."""
    config_path = domain_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml in domain pack: {domain_dir}")
    return DomainConfig.from_yaml(config_path)
