"""Domain-pack loading and configuration.

The pipeline is domain-agnostic: it reads a domain pack (prompts + config)
from docs/domain/<domain>/ and never hard-codes domain terms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from onto3gpp.llm import LLMConfig


@dataclass
class EmbedConfig:
    """Embedding configuration (swappable local/API).

    ``api_key_env`` names the env var for the secret (e.g. ``COMMAND_CODE_API_KEY``
    for ``cmdc``, ``OPENAI_API_KEY`` for ``openai``; omit for ``ollama``).
    """

    kind: str = "hash"  # hash | tfidf | ollama | api | gguf
    dim: int = 384
    api_base: str | None = None
    model: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    # GGUF-specific (used when kind=gguf)
    repo_id: str | None = None
    filename: str | None = None
    model_path: str | None = None
    n_ctx: int | None = None
    n_batch: int | None = None
    n_gpu_layers: int | None = None
    threshold: float = 0.25
    top_k: int = 5

    def to_embedder_cfg(self) -> dict:
        d: dict = {"kind": self.kind, "dim": self.dim}
        if self.api_base:
            d["api_base"] = self.api_base
        if self.model:
            d["model"] = self.model
        if self.api_key:
            d["api_key"] = self.api_key
        if self.api_key_env:
            d["api_key_env"] = self.api_key_env
        if self.repo_id:
            d["repo_id"] = self.repo_id
        if self.filename:
            d["filename"] = self.filename
        if self.model_path:
            d["model_path"] = self.model_path
        if self.n_ctx is not None:
            d["n_ctx"] = self.n_ctx
        if self.n_batch is not None:
            d["n_batch"] = self.n_batch
        if self.n_gpu_layers is not None:
            d["n_gpu_layers"] = self.n_gpu_layers
        return d


@dataclass
class DomainConfig:
    """Configuration loaded from a domain pack's config.yaml."""

    domain: str
    intents: list[str] = field(default_factory=list)
    intent_patterns: dict[str, list[str]] = field(default_factory=dict)
    document_metadata: list[str] = field(default_factory=list)
    judge_threshold: float = 0.8
    llm: LLMConfig = field(default_factory=LLMConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> DomainConfig:
        """Load a DomainConfig from a config.yaml file."""
        import os as _os

        data = yaml.safe_load(path.read_text())
        # Allow api_key to come from env when config leaves it null
        # (so the key stays out of git). Checked before LLMConfig.
        llm_data = data.get("llm")
        if isinstance(llm_data, dict) and llm_data.get("default", {}).get("api_key") is None:
            env_key = _os.getenv("COMMAND_CODE_API_KEY") or _os.getenv("OPENAI_API_KEY")
            if env_key:
                default = llm_data.setdefault("default", {})
                if default.get("api_key") is None:
                    default["api_key"] = env_key
        llm = LLMConfig.from_dict(data.pop("llm", None))
        embed_data = data.pop("embed", None)
        # filter unknown keys defensively (include api_key_env for declarative wiring)
        if isinstance(embed_data, dict):
            known = {"kind", "dim", "api_base", "model", "api_key", "api_key_env", "threshold", "top_k"}
            filtered = {k: v for k, v in embed_data.items() if k in known}
            embed = EmbedConfig(**filtered)
            # Resolve declarative api_key via api_key_env
            if not embed.api_key and embed.api_key_env:
                env_val = _os.getenv(embed.api_key_env)
                if env_val:
                    embed.api_key = env_val
            # legacy fallback only if no declarative wiring
            elif not embed.api_key and not embed.api_key_env:
                ek = _os.getenv("COMMAND_CODE_API_KEY") or _os.getenv("OPENAI_API_KEY")
                if ek:
                    embed.api_key = ek
        else:
            embed = EmbedConfig(**embed_data) if isinstance(embed_data, dict) else EmbedConfig()
        return cls(**data, llm=llm, embed=embed)


def load_domain(domain_dir: Path) -> DomainConfig:
    """Load a domain pack from a directory containing config.yaml."""
    config_path = domain_dir / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"No config.yaml in domain pack: {domain_dir}")
    return DomainConfig.from_yaml(config_path)


def load_tbox(domain_dir: Path) -> TBox:
    """Load the TBox from a domain pack's tbox.yaml."""
    from onto3gpp.ontology.tbox import tbox_from_dict

    tbox_path = domain_dir / "tbox.yaml"
    if not tbox_path.exists():
        raise FileNotFoundError(f"No tbox.yaml in domain pack: {domain_dir}")
    data = yaml.safe_load(tbox_path.read_text())
    return tbox_from_dict(data)
