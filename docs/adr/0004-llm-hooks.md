# ADR-0004: Configurable External AI Hooks (LiteLLM-backed)

- **Status:** Accepted
- **Date:** 2026-08-24
- **Stage:** 4 (AI-as-Judge Improvement Loop)

## Context

The pipeline is deterministic and AI-free at runtime, but the offline
build/improve/evaluate stages may use an LLM as a knowledge engineer and
judge. The user requires **hooks for the app to be able to use / configure
external AI models** — i.e. the AI backend must be swappable and
configurable per domain pack, not hard-coded to one provider.

We need a single seam where an external AI model can be plugged in, used by
the judge, the extractor, and the improvement loop, and disabled by default
so the pipeline still runs with zero AI cost.

## Decision

Introduce a thin **LLM client abstraction** (`src/onto3gpp/llm.py`) wrapping
**LiteLLM** (`litellm.completion`), which supports OpenAI, Anthropic, local
vLLM/ollama, and many providers behind one interface.

- **`LLMConfig`** — dataclass (enabled, model, provider, api_base, api_key,
  temperature, max_tokens, extra). Built from the domain pack's `config.yaml`
  `llm:` section via `LLMConfig.from_dict` (unknown keys → `extra`).
- **`LLMClient`** — `complete(prompt)` / `complete_json(prompt)`; raises
  `LLMDisabledError` when disabled. Subclasses override `_call` to use any
  other backend.
- **Wiring:** `DomainConfig.llm` field; `docs/domain/3gpp/config.yaml` gains an
  `llm:` section (default `enabled: false`).
- **Consumers:**
  - `llm_judge_candidate` (judge.py) — AI-as-judge path using the
    `judge_candidates.txt` prompt, with **fallback to the deterministic
    judge** on malformed/unavailable responses.
  - `propose_improvements` + `apply_proposals` (improve/) — the improvement
    loop: log analysis → LLM proposals → referential-integrity review.

## Consequences

- **Positive:** one swappable AI seam; domain packs configure their own model;
  deterministic by default (zero AI cost); LiteLLM gives provider breadth
  without vendor lock-in; local vLLM/ollama supported for offline/private use.
- **Negative:** LiteLLM is a heavy dependency; API-key handling must be
  careful (env vars preferred over config-file secrets).
- **Trade-off:** the deterministic judge remains the default; the LLM judge is
  an opt-in enhancement. The runtime query path is untouched (still AI-free).

## Alternatives Considered

- **Direct OpenAI SDK** — rejected: vendor lock-in, no local-model support.
- **Custom provider adapters per vendor** — rejected: more code, no benefit
  over LiteLLM's unified interface.
- **No LLM hooks** — rejected: the user explicitly requires configurable
  external AI model hooks for the app.

## Open Questions

- Should the LLM judge's verdicts be logged for auditability alongside the
  deterministic judge's?
- How to calibrate the LLM judge's confidence threshold against the
  deterministic judge's?
