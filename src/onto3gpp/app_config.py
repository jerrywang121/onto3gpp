"""App-level AI configuration loader (ADR-0015).

Loads ``config/app.yaml`` which owns ``providers`` (per-provider wiring) +
``llm`` (enabled + default + per-task ``models``) and ``embed``. Domain packs
no longer contain AI config. Providers map keeps api_base/api_key_env once;
llm entries just reference provider name (DRY). Supports legacy direct fields
for backward compat.
Each provider entry may declare ``api_base`` / ``api_key`` / ``api_key_env``
(e.g. ``COMMAND_CODE_API_KEY`` for ``cmdc``, ``OPENAI_API_KEY`` for ``openai``;
omit for ``ollama``). The actual key never lives in YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from onto3gpp.config import EmbedConfig
from onto3gpp.llm import LLMConfig


@dataclass
class AppConfig:
    """App-level AI config (provider/model + embedding)."""

    llm: LLMConfig
    embed: EmbedConfig
    providers: dict = field(default_factory=dict)


def _resolve_key(explicit: str | None, env_name: str | None) -> str | None:
    if explicit:
        return explicit
    if env_name:
        return os.getenv(env_name) or None
    return None


def _apply_provider(d: dict, providers: dict) -> None:
    """Mutate ``d`` in-place: fill missing api_base/api_key/api_key_env from providers[provider]."""
    if not isinstance(d, dict) or not providers:
        return
    prov = d.get("provider")
    if prov and prov in providers and isinstance(providers[prov], dict):
        p = providers[prov]
        for k in ("api_base", "api_key", "api_key_env"):
            if d.get(k) is None and p.get(k) is not None:
                d[k] = p[k]


def _load_embed(data: dict | None, providers: dict | None = None) -> EmbedConfig:
    if not isinstance(data, dict):
        return EmbedConfig()
    # Allow embed to reference a provider: {provider: cmdc, kind: api, model: ...}
    # Fill missing api_base/api_key/api_key_env from providers map.
    if providers and data.get("provider") and data["provider"] in providers:
        p = providers[data["provider"]]
        for k in ("api_base", "api_key", "api_key_env"):
            if data.get(k) is None and isinstance(p, dict) and p.get(k) is not None:
                data = dict(data)
                data[k] = p[k]
    known = {"kind", "dim", "api_base", "model", "api_key", "api_key_env", "repo_id", "filename", "model_path", "n_ctx", "num_ctx", "n_batch", "n_gpu_layers", "threshold", "top_k", "provider"}
    filtered = {k: v for k, v in data.items() if k in known}
    # provider is not on EmbedConfig yet — strip it before construction, keep wiring via api_* fields
    filtered.pop("provider", None)
    cfg = EmbedConfig(**{k: v for k, v in filtered.items() if k in EmbedConfig.__dataclass_fields__})
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
        return AppConfig(llm=LLMConfig(), embed=EmbedConfig(), providers={})

    providers = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}
    # Normalize providers: allow short form `cmdc: {api_base: ..., api_key_env: ...}` where provider field omitted -> key is provider name
    # Empty dicts (e.g. `ollama: {}`) become a provider with just the name.
    normalized_providers: dict = {}
    for k, v in providers.items():
        if isinstance(v, dict):
            nv = dict(v)
            nv.setdefault("provider", k)
            normalized_providers[k] = nv
        elif v is None:
            normalized_providers[k] = {"provider": k}
        else:
            normalized_providers[k] = v
    providers = normalized_providers

    # llm: resolve via providers before/from_dict so tasks just name provider.
    # _apply_provider only fills missing api_base/api_key/api_key_env, so
    # cross-provider leakage is prevented by only filling when the task's
    # provider key matches the provider being applied (which it does — we
    # apply exactly the provider named by the task).
    llm_data = raw.get("llm")
    if isinstance(llm_data, dict) and providers:
        # Work on a copy
        llm_data = dict(llm_data)
        # Apply provider to default
        if isinstance(llm_data.get("default"), dict):
            llm_data["default"] = dict(llm_data["default"])
            _apply_provider(llm_data["default"], providers)
        elif "default" not in llm_data and llm_data.get("provider") in providers:
            # flat form may already be at llm level? treat as default
            _apply_provider(llm_data, providers)
        # Apply provider to each model
        if isinstance(llm_data.get("models"), dict):
            nmodels = {}
            for task, cfg in llm_data["models"].items():
                if isinstance(cfg, dict):
                    cfg = dict(cfg)
                    _apply_provider(cfg, providers)
                nmodels[task] = cfg
            llm_data["models"] = nmodels
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
        # Inherit api_key_env from default only when same provider (so ollama
        # doesn't pick up COMMAND_CODE_API_KEY). LLMConfig.from_dict already
        # handles this; this is just env resolution for the inherited name.
        if not task_cfg.api_key_env and llm.api_key_env and task_cfg.provider == llm.provider:
            task_cfg.api_key_env = llm.api_key_env
            if not task_cfg.api_key:
                env_val = os.getenv(llm.api_key_env)
                if env_val:
                    task_cfg.api_key = env_val

    embed = _load_embed(raw.get("embed") if isinstance(raw.get("embed"), dict) else None, providers)
    return AppConfig(llm=llm, embed=embed, providers=providers)
