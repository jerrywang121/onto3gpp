"""App-level AI configuration loader (ADR-0015).

Loads ``config/app.yaml`` which owns ``llm`` (enabled + default + per-task
``models``) and ``embed``. Domain packs no longer contain AI config.
Each entry may declare ``api_key_env: <ENV_NAME>`` to bind a secret via env
(e.g. ``COMMAND_CODE_API_KEY`` for ``cmdc``, ``OPENAI_API_KEY`` for ``openai``;
omit for ``ollama``). The actual key never lives in YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from onto3gpp.config import EmbedConfig
from onto3gpp.llm import LLMConfig


@dataclass
class AppConfig:
    """App-level AI config (provider/model + embedding)."""

    llm: LLMConfig
    embed: EmbedConfig


def _resolve_key(explicit: str | None, env_name: str | None) -> str | None:
    if explicit:
        return explicit
    if env_name:
        return os.getenv(env_name) or None
    return None


def _load_embed(data: dict | None) -> EmbedConfig:
    if not isinstance(data, dict):
        return EmbedConfig()
    known = {"kind", "dim", "api_base", "model", "api_key", "api_key_env", "threshold", "top_k"}
    filtered = {k: v for k, v in data.items() if k in known}
    cfg = EmbedConfig(**filtered)
    # Resolve api_key via declarative wiring if not already set.
    if not cfg.api_key and cfg.api_key_env:
        cfg.api_key = os.getenv(cfg.api_key_env) or None
    return cfg


def load_app_config(path: Path | None = None) -> AppConfig:
    """Load app config from ``path`` (or auto-discover ``config/app.yaml``).

    If ``path`` is None, searches upward from CWD and repo root for
    ``config/app.yaml``; if not found, returns defaults (LLM disabled, hash embed).
    """
    raw: dict | None = None
    if path is not None:
        if not path.exists():
            raise FileNotFoundError(f"No app config at: {path}")
        raw = yaml.safe_load(path.read_text()) or {}
    else:
        # Auto-discover: try ./config/app.yaml, then repo root via pyproject.toml walk
        candidates = [Path("config/app.yaml"), Path("config/app.yaml").resolve()]
        # Walk up to find repo root (pyproject.toml)
        cur = Path.cwd().resolve()
        for _ in range(6):
            cand = cur / "config" / "app.yaml"
            if cand.exists():
                candidates.insert(0, cand)
                break
            cur = cur.parent
        for cand in candidates:
            if cand.exists():
                raw = yaml.safe_load(cand.read_text()) or {}
                break

    if raw is None:
        return AppConfig(llm=LLMConfig(), embed=EmbedConfig())

    # llm: resolve api_key via api_key_env (LLMConfig.from_dict already handles inheritance,
    # but we also resolve env for the default and each task here so api_key is populated).
    llm_data = raw.get("llm")
    llm = LLMConfig.from_dict(llm_data if isinstance(llm_data, dict) else None)
    # Resolve default api_key via its api_key_env if needed
    if not llm.api_key and llm.api_key_env:
        env_val = os.getenv(llm.api_key_env)
        if env_val:
            llm.api_key = env_val
    for task_cfg in llm.models.values():
        if not task_cfg.api_key and task_cfg.api_key_env:
            env_val = os.getenv(task_cfg.api_key_env)
            if env_val:
                task_cfg.api_key = env_val
        # Inherit api_key_env from default if not set (LLMConfig.from_dict already does,
        # but also handle env resolution for inherited env name).
        if not task_cfg.api_key_env and llm.api_key_env:
            task_cfg.api_key_env = llm.api_key_env
            if not task_cfg.api_key:
                env_val = os.getenv(llm.api_key_env)
                if env_val:
                    task_cfg.api_key = env_val

    embed = _load_embed(raw.get("embed") if isinstance(raw.get("embed"), dict) else None)
    return AppConfig(llm=llm, embed=embed)
