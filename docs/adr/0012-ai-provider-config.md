# ADR-0012: AI Provider / Model Configuration Surface

- **Status:** Accepted
- **Date:** 2026-08-25
- **Stage:** 8 (AI provider/model configuration surface)
- **Related:** ADR-0004, ADR-0011

## Context

The app exposes an **AI provider / model configuration surface** so users can
plug in different AI backends and models. Today the `llm:` section in the
domain pack's `config.yaml` supports a **single model**:

```yaml
llm:
  enabled: false
  model: gpt-4o-mini
  provider: null
  api_base: null
  api_key: null
  temperature: 0.0
  max_tokens: 1024
```

But the ingestion pipeline (ADR-0011) has **multiple distinct tasks** with
different cost/quality needs: domain detection (cheap, low tokens), extraction
(medium), judging (higher quality), alignment (cheap), merge (medium),
improvement (medium). A single model forces a one-size-fits-all trade-off and
prevents routing cheap tasks to cheap models and hard tasks to strong models.

## Decision

Extend the `llm:` section to support **multiple named models** with a
**task → model routing map**:

```yaml
llm:
  enabled: false
  default: {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
  models:
    extract:       {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
    judge:         {provider: openai, model: gpt-4o,      temperature: 0.0, max_tokens: 1024}
    align:         {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
    merge:         {provider: ollama, model: llama3,     api_base: http://localhost:11434}
    domain_detect: {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 256}
    improve:       {provider: openai, model: gpt-4o-mini, temperature: 0.0, max_tokens: 1024}
```

- Each task resolves to a model; a task with no explicit entry falls back to
  `default`.
- `LLMConfig` gains a `models: dict[str, LLMConfig]` map and a `default`.
- `LLMClient` becomes a **router**: `client.for_task("judge")` returns a client
  bound to the task's model config.
- Backward compatible: a flat `model:`/`provider:`/`api_base:`/`api_key:` block
  is treated as the `default`.
- Deterministic by default (`enabled: false`); the runtime query path is always
  AI-free.

## Options Considered

- **Single model (status quo).** Rejected: one-size-fits-all cost/quality
  trade-off; can't route cheap tasks to cheap models.
- **Multi-model routing (chosen).** Per-task model selection; cheap tasks use
  cheap models, hard tasks use strong models; supports mixed local/cloud
  backends (e.g. local ollama for merge, cloud for judge).
- **Global model registry (env/CLI only).** Rejected: less discoverable and
  not domain-pack-driven.

## Rationale

- Matches the requirement to "expose a surface for AI provider / model
  configuration."
- Per-task routing optimizes cost and quality across the ingestion pipeline.
- Domain-pack-driven keeps it domain-general and reproducible.
- Backward compatible with the existing single-model config.

## Consequences

- **Positive:** flexible, cost-optimized, domain-pack-driven AI configuration;
  supports mixed local/cloud backends.
- **Negative:** more config surface to document; a task with no model entry
  silently falls back to `default` (must be documented).
- **Trade-off:** we accept a slightly larger config schema for per-task
  control.

## Amendment (ADR-0015, 2026-08-28)

AI provider/model config is **app-level** (`config/app.yaml`), not domain-level.
Domain packs no longer contain `llm:`/`embed:` — they keep only
`domain`/`intents`/`intent_patterns`/`document_metadata`/`judge_threshold`.
Each entry in `config/app.yaml` declares `api_key_env: <ENV_NAME>` (e.g.
`COMMAND_CODE_API_KEY` for `cmdc`, `OPENAI_API_KEY` for `openai`; omit for
`ollama`) so provider keys are wired declaratively — swapping `cmdc`↔`openai`
↔`ollama` is a one-line change in `config/app.yaml` with `api_key: null`
(no secret in git).

## Open Questions

- Should model configs be overridable via environment variables / CLI flags
  (e.g. `--llm-model judge=gpt-4o`)?
- Should the router support per-task retries / timeouts?
