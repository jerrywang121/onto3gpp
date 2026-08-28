# ADR-0015: App-Level AI Provider / Model Configuration

- **Status:** Accepted
- **Date:** 2026-08-28
- **Stage:** 8/9
- **Related:** ADR-0002, ADR-0012, ADR-0014

## Context

AI provider/model config (`llm:` + `embed:`) lived in domain packs (`docs/domain/*/config.yaml`). This made every domain edit touch AI wiring, prevented portable copy of `_template` (each new domain would have to edit provider secrets), and forced secrets adjacent to domain intents. The plan `docs/superpowers/plans/2026-08-28-app-level-ai-config.md` calls for a portable, swappable surface.

## Decision

- Single app-level file `config/app.yaml` owns `providers:` (per-provider wiring) + `llm:` (enabled + default + per-task models) + `embed:`. `providers:` holds `api_base`/`api_key_env` once; `llm` entries just reference `provider: <name>` (DRY).
- Each provider entry declares `api_key_env: <ENV_NAME>` (e.g. `COMMAND_CODE_API_KEY` for `cmdc`, `OPENAI_API_KEY` for `openai`; omit for `ollama`). The actual key never lives in YAML.
- `LLMConfig.api_key_env` + `EmbedConfig.api_key_env`; resolver `_resolve_api_key(explicit, api_key_env)` prefers explicit → `os.getenv(api_key_env)` → legacy fallback (for backward compat).
- `src/onto3gpp/app_config.py` `AppConfig(llm, embed)` and `load_app_config(path|auto-discover)` resolve keys via declarative env names, with default inheritance.
- CLI gains `--app-config PATH` (defaults to `config/app.yaml` if present) for `ingest`/`improve`; `load_domain` no longer owns AI wiring. Legacy `llm:`/`embed:` in domain packs still parsed with deprecation (app wins).
- `DomainConfig` (`docs/domain/*/config.yaml`) keeps only `domain`, `intents`, `intent_patterns`, `document_metadata`, `judge_threshold`.

## Options Considered

- Keep AI config in domain packs (status quo): rejected — not portable, couples secrets to domains.
- Env/CLI-only registry: rejected — not discoverable, not domain-general.

## Consequences

- New domains are `cp -r _template my-domain` and edit `config/app.yaml` once to swap providers (one-line: `cmdc`/`openai`/`ollama`).
- No secrets in repo (`api_key: null` + `api_key_env` name); `.env` stays `.gitignore`d.
- Slightly more files; but app config is single source of truth, domains are AI-free.
