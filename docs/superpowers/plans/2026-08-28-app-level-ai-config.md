# App-Level AI Provider Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move AI provider/model (LLM + embedding) configuration from domain packs (`docs/domain/<domain>/config.yaml` `llm:`/`embed:`) to an app-level config so domains stay portable and users can swap providers (cmdc→`COMMAND_CODE_API_KEY`, openai→`OPENAI_API_KEY`, ollama→no key) without editing domain packs.

**Architecture:** New `config/app.yaml` (repo-root `config/` dir) owns `llm:` (enabled + default + per-task `models:` map) and `embed:` (kind/dim/threshold/top_k + api/ollama). Each model/entry declares `api_key_env: <ENV_NAME>` (or omits for ollama); loader resolves `api_key` via `os.getenv(api_key_env)` with `api_key` literal taking precedence. `DomainConfig` drops/stops requiring `llm`/`embed` (kept as deprecated fallback with warning). `LLMConfig`/`EmbedConfig` gain `api_key_env` field + env-aware resolver (replaces hardcoded `COMMAND_CODE_API_KEY`). CLI gains `--app-config` (defaults to `config/app.yaml` if present) and wires `LLMClient`/`EmbeddingIndex` from app config; `load_domain` no longer owns AI wiring.

**Tech Stack:** Python 3.11, PyYAML, LiteLLM (`litellm.completion`), `src/onto3gpp/llm.py` (`LLMConfig`/`LLMClient`), `src/onto3gpp/config.py` (`DomainConfig`/`EmbedConfig`/`load_domain`), `src/onto3gpp/embed/` (Hash/TfIdf/Ollama/Api), Click CLI (`src/onto3gpp/cli.py`).

## Global Constraints

- Python >=3.11, `pyyaml>=6.0`, `litellm>=1.40`, `click>=8.1`; no new runtime deps.
- Deterministic runtime stays AI-free/CPU-only when `llm.enabled: false` (AGENTS.md §0.1).
- Domain-general: no hard-coded 3GPP terms; domains remain copy-`_template` portable (ADR-0002).
- No secrets in repo: `config/app.yaml` commits `api_key: null` + `api_key_env: COMMAND_CODE_API_KEY` (name, not value); actual key lives in `.env`/`env` and is `.gitignore`d.
- Preserve user's current `cmdc`/`minimax/minimax-m3-free` provider edits in `docs/domain/3gpp/config.yaml` — do NOT revert; migrate them to `config/app.yaml` verbatim.
- Wire `COMMAND_CODE_API_KEY` declaratively via `api_key_env` in YAML, not hardcoded `_COMMAND_CODE_ENV` fallback — must support `cmdc→COMMAND_CODE_API_KEY`, `openai→OPENAI_API_KEY`, `ollama→(no key)` swappable.
- `pyproject.toml` `tool.pytest` `testpaths = ["tests"]` `addopts = "-q -n auto"`; TDD/SDD required.

---

## File Structure

```
config/
  app.yaml                 # NEW — app-level AI config (llm + embed), committed with api_key: null
src/onto3gpp/
  config/
    __init__.py            # NEW package (or keep src/onto3gpp/config.py as package entry)
    app.py                 # NEW — AppConfig loader (LLM + embed, api_key_env resolver)
    domain.py              # REFACTOR — DomainConfig without llm/embed (or deprecated fallback)
  # OR keep monolithic src/onto3gpp/config.py but split AppConfig vs DomainConfig inside
  config.py                # MODIFY — add AppConfig/AppLLM wiring, keep DomainConfig for compat; OR split
  llm.py                   # MODIFY — LLMConfig gains api_key_env, _resolve_api_key respects it
  embed/
    embed.py               # MODIFY — ApiEmbedder/Ollama respects api_key_env via AppConfig
  cli.py                   # MODIFY — add --app-config, load_app_config(), wire clients
docs/domain/
  _template/config.yaml    # MODIFY — remove llm:/embed: blocks (or comment as deprecated, point to config/app.yaml)
  3gpp/config.yaml         # MODIFY — remove/migrate llm:/embed: to config/app.yaml; keep intents/metadata/judge_threshold only
docs/
  architecture.md          # MODIFY — §3.1.1: AI config lives in config/app.yaml, not domain pack
  adr/0012-ai-provider-config.md  # MODIFY — add § App-Level amendment (ADR-0015 or update)
  adr/0015-app-level-ai-config.md # NEW — decision to move AI config to app level
tests/
  test_app_config.py       # NEW — AppConfig loading, api_key_env resolution, provider swappability
  test_config_embed.py     # MODIFY — reflect new locations
  test_llm_routing.py      # MODIFY — routing now via AppConfig
  test_cli_app_config.py   # NEW — --app-config override + default discovery
```

Alternative if keeping single file: `src/onto3gpp/config.py` exports both `DomainConfig` and `AppConfig` without a sub-package. Prefer single `config.py` + new `app_config.py` to minimize churn; plan shows both.

---

### Task 1: App-Level Config Schema & Loader (TDD)

**Files:**
- Create: `config/app.yaml`
- Create: `src/onto3gpp/app_config.py` (or `src/onto3gpp/config/app.py`)
- Modify: `src/onto3gpp/llm.py`
- Modify: `src/onto3gpp/embed/embed.py` (minor)
- Test: `tests/test_app_config.py`

**Interfaces:**
- Consumes: YAML file at `config/app.yaml` (or path passed to `load_app_config`)
- Produces:
  - `@dataclass AppConfig(llm: LLMConfig, embed: EmbedConfig)`
  - `def load_app_config(path: Path | None) -> AppConfig`  # None → search repo root config/app.yaml → defaults
  - `LLMConfig.api_key_env: str | None` + resolver `def _resolve_api_key(explicit, api_key_env) -> str | None`
  - `EmbedConfig.api_key_env: str | None`

- [ ] **Step 1: Write failing test — app config loads cmdc with api_key_env**

```python
# tests/test_app_config.py
def test_app_config_cmdc_resolves_env(tmp_path, monkeypatch):
    monkeypatch.setenv("COMMAND_CODE_API_KEY", "user_test_123")
    p = tmp_path / "app.yaml"
    p.write_text("""
llm:
  enabled: true
  default:
    provider: cmdc
    model: minimax/minimax-m3-free
    api_base: https://api.commandcode.ai/provider/v1
    api_key_env: COMMAND_CODE_API_KEY
embed:
  kind: hash
  dim: 384
""")
    from onto3gpp.app_config import load_app_config
    cfg = load_app_config(p)
    assert cfg.llm.enabled is True
    assert cfg.llm.provider == "cmdc"
    # resolver should have populated api_key from env via api_key_env
    assert cfg.llm.api_key == "user_test_123"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_app_config.py::test_app_config_cmdc_resolves_env -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'onto3gpp.app_config'` / `AssertionError`

- [ ] **Step 3: Create `config/app.yaml` (migrated from user's 3gpp edits, no secret)**

```yaml
# config/app.yaml — app-level AI provider/model config (domain-agnostic)
# api_key stays out of git: set api_key_env and put the value in .env (COMMAND_CODE_API_KEY, OPENAI_API_KEY, etc.)
# Copy provider/model values verbatim from docs/domain/3gpp/config.yaml (user's cmdc/minimax edits).
llm:
  enabled: true
  default:
    provider: cmdc
    model: minimax/minimax-m3-free
    api_base: https://api.commandcode.ai/provider/v1
    api_key: null
    api_key_env: COMMAND_CODE_API_KEY
    temperature: 0.5
    max_tokens: 4096
  models:
    extract:       {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.1, max_tokens: 4096}
    verify:        {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.3, max_tokens: 4096}
    relations:     {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.3, max_tokens: 4096}
    judge:         {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.5, max_tokens: 4096}
    align:         {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.5, max_tokens: 4096}
    merge:         {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.5, max_tokens: 4096}
    domain_detect: {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.5, max_tokens: 2048}
    improve:       {provider: cmdc, model: minimax/minimax-m3-free, api_key_env: COMMAND_CODE_API_KEY, temperature: 0.8, max_tokens: 4096}
  # examples for swapping:
  # openai: {provider: openai, model: gpt-4o-mini, api_key_env: OPENAI_API_KEY}
  # ollama local (no key): {provider: ollama, model: llama3, api_base: http://localhost:11434}
embed:
  kind: hash
  dim: 384
  threshold: 0.25
  top_k: 5
  api_key: null
  api_key_env: null
  # ollama example: {kind: ollama, api_base: http://localhost:11434, model: embeddinggemma:300m, dim: 768}
  # api example:   {kind: api, api_base: https://api.openai.com/v1, model: text-embedding-3-small, dim: 1536, api_key_env: OPENAI_API_KEY}
  # cmdc embed:    {kind: api, api_base: https://api.commandcode.ai/provider/v1, model: <embedding-model>, dim: <dim>, api_key_env: COMMAND_CODE_API_KEY}
```

Add `config/` to repo (ensure `config/app.yaml` is tracked, `.env` is ignored already).

- [ ] **Step 4: Implement `LLMConfig.api_key_env` + resolver and `AppConfig` loader**

In `src/onto3gpp/llm.py`:
- Add field `api_key_env: str | None = None` to `LLMConfig`.
- Update `from_dict` known set to include `api_key_env`; propagate `api_key_env` from `default` to per-task models like `api_base`/`api_key`/`provider` (if not set, inherit).
- Change `_resolve_api_key(explicit, api_key_env=None)` to: `explicit` → `os.getenv(api_key_env)` if set → fallback `os.getenv("COMMAND_CODE_API_KEY") or os.getenv("OPENAI_API_KEY")` only if `api_key_env` is None (or keep as generic fallback for backward compat, but declarative takes precedence). Remove hardcoded `_COMMAND_CODE_ENV` constant or keep as fallback only.
- Ensure `LLMClient._call` calls `_resolve_api_key(self.config.api_key, self.config.api_key_env)`.

Create `src/onto3gpp/app_config.py`:
```python
from dataclasses import dataclass
from pathlib import Path
import os, yaml
from onto3gpp.llm import LLMConfig
from onto3gpp.config import EmbedConfig  # or define locally

@dataclass
class AppConfig:
    llm: LLMConfig
    embed: EmbedConfig

def load_app_config(path: Path | None = None) -> AppConfig: ...
# resolves api_key via api_key_env, handles api_key null, searches repo root config/app.yaml if path is None
```

Handle `EmbedConfig.api_key_env` similarly: add field, resolver, `to_embedder_cfg` includes `api_key_env` handling, `ApiEmbedder` uses `api_key or os.getenv(api_key_env)`.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_app_config.py -v`
Expected: PASS (cmdc env resolved, openai/ollama cases)

- [ ] **Step 6: Add swappability tests**

```python
def test_openai_env(monkeypatch, tmp_path):  # openai provider → OPENAI_API_KEY
def test_ollama_no_key(tmp_path):            # ollama → api_key None even though env set
def test_explicit_api_key_overrides_env(tmp_path, monkeypatch): # literal api_key wins
```

Run: `.venv/bin/python -m pytest tests/test_app_config.py -v`

- [ ] **Step 7: Commit**

Message: `feat(config): app-level AI provider config with api_key_env wiring` (include `config/app.yaml` + `app_config.py` + `llm.py` changes)

---

### Task 2: Wire CLI & Pipeline to App Config (TDD)

**Files:**
- Modify: `src/onto3gpp/cli.py`
- Modify: `src/onto3gpp/config.py` (deprecate DomainConfig.llm/embed or make optional)
- Test: `tests/test_cli_app_config.py`, `tests/test_cli_llm_override.py` (update)

**Interfaces:**
- Consumes: `AppConfig` via `load_app_config(path)`
- Produces: CLI `--app-config PATH` option; `ingest`/`improve`/`evaluate` resolve LLM/Embed from app config, not domain pack

- [ ] **Step 1: Write failing test — CLI --app-config overrides**

```python
def test_cli_ingest_uses_app_config(tmp_path):
    # create app.yaml with cmdc, domain pack without llm, run ingest --app-config
    # assert LLMClient was constructed with cmdc model
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_app_config.py -v`
Expected: FAIL (option not recognized / still reads domain llm)

- [ ] **Step 3: Implement CLI wiring**

- Add `def _load_app_config(app_config: Path | None) -> AppConfig` helper that tries `app_config` if given, else `Path("config/app.yaml")` if exists, else defaults (disabled).
- Add `@click.option("--app-config", type=click.Path(path_type=Path), default=None, help="Path to app-level AI config (default: config/app.yaml if present)")` to commands that need LLM/Embed: `ingest`, `improve`, `align` (if it judges), `eval` (if needed). Keep `--domain` for domain pack.
- In each command, `app_cfg = _load_app_config(app_config)` then `llm = LLMClient(app_cfg.llm)` and embed via `app_cfg.embed.to_embedder_cfg()` instead of `cfg.llm`/`cfg.embed`.
- Keep fallback: if `config/app.yaml` missing and domain pack still has `llm`, emit `DeprecationWarning` and use `cfg.llm` (backward compat for tests). Domain pack without llm + no app config → disabled LLM.
- Update `src/onto3gpp/config.py`: make `DomainConfig.llm`/`embed` optional/deprecated (still parsed but warn if present and app config also present — app wins).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli_app_config.py tests/test_cli_llm_override.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

Message: `feat(cli): wire --app-config and app-level LLM/embedding into ingest/improve`

---

### Task 3: Migrate Domain Packs (Domain-General Cleanup)

**Files:**
- Modify: `docs/domain/3gpp/config.yaml`
- Modify: `docs/domain/_template/config.yaml`
- Modify: `docs/domain/3gpp/README.md` / `docs/domain/_template/README.md` (if they document llm:)

**Interfaces:**
- Produces: Domain packs with `llm:`/`embed:` removed (or commented as deprecated pointing to `config/app.yaml`)

- [ ] **Step 1: Move llm/embed blocks out of 3gpp pack**

- Cut the entire `embed:` and `llm:` blocks from `docs/domain/3gpp/config.yaml` and paste them into `config/app.yaml` (already done in Task 1 — ensure verbatim match to user's cmdc edits: provider cmdc, model minimax/minimax-m3-free, api_base https://api.commandcode.ai/provider/v1, all 8 tasks).
- Leave `docs/domain/3gpp/config.yaml` with only: `domain`, `intents`, `intent_patterns`, `document_metadata`, `judge_threshold`. Add header comment: `# AI provider/model config lives in config/app.yaml (app-level, not domain-level). See ADR-0015.`
- Do NOT revert user's provider edits — they now live in `config/app.yaml`; verify diff shows move, not deletion.

- [ ] **Step 2: Update _template**

- Remove `llm:`/`embed:` from `docs/domain/_template/config.yaml`; replace with comment: `# AI config is app-level: copy config/app.yaml and set api_key_env per provider (cmdc→COMMAND_CODE_API_KEY, openai→OPENAI_API_KEY, ollama→no key).`
- Add `config/app.yaml` template snippet as comment if helpful.

- [ ] **Step 3: Verify no secret leaked**

Run: `git diff -- config/app.yaml docs/domain/3gpp/config.yaml | grep -i api_key` — should show `api_key: null` and `api_key_env: COMMAND_CODE_API_KEY`, NOT a literal key value.
Run: `git check-ignore -v .env` — should be ignored.

- [ ] **Step 4: Commit**

Message: `refactor(domain): move llm/embed to app-level config (domain packs portable)`

---

### Task 4: Docs — ADR + Architecture + Roadmap/Status

**Files:**
- Create: `docs/adr/0015-app-level-ai-config.md`
- Modify: `docs/adr/0012-ai-provider-config.md` (add amendment note)
- Modify: `docs/architecture.md` (§3.1.1, §3.2)
- Modify: `docs/roadmap.md` / `docs/status.md` (Stage 8/9 notes)
- Modify: `README.md` (config docs table)

- [ ] **Step 1: Write ADR-0015**

Decision: AI provider/model config is app-level (`config/app.yaml`), not domain-level. Rationale: domains stay portable (copy `_template` needs no AI edits), provider swapping is one-file change with declarative `api_key_env` wiring per provider. Consequences: domain packs no longer contain `llm`/`embed`; app config is the source of truth; env var names are config-driven, not hardcoded.

- [ ] **Step 2: Patch architecture.md**

Change "domain pack's config.yaml `llm:` section" to "app config `config/app.yaml` `llm:` section (domain packs are AI-free)". Update §3.2 tree to show `config/app.yaml` alongside `docs/domain/`.

- [ ] **Step 3: Commit**

Message: `docs(adr): ADR-0015 app-level AI config, update architecture`

---

### Task 5: Verification — Pytest + Eval Harness (Evidence)

**Files:** none (verification only)

- [ ] **Step 1: Run full pytest**

Run: `.venv/bin/python -m pytest -q`
Expected: all green (update `tests/test_config_embed.py`, `tests/test_smoke.py:test_load_domain_pack` which currently asserts domain llm — adjust to check AppConfig instead)

- [ ] **Step 2: Run eval harness with app config**

Run: `.venv/bin/python -m onto3gpp eval --parsed data/parsed --gold data/gold_queries_38300.jsonl --top-k 10` (should work with or without --app-config; llm not needed for plain BM25 but ingest should use app config)
Run: `COMMAND_CODE_API_KEY=dummy .venv/bin/python -c "from pathlib import Path; from onto3gpp.app_config import load_app_config; c=load_app_config(Path('config/app.yaml')); print(c.llm.provider, c.llm.model, bool(c.llm.api_key))"`

- [ ] **Step 3: Record metrics in docs/status.md if ingest path changed**

If `ingest` behavior changed, re-run ingest eval and record; otherwise note "no metric change — config move only".

- [ ] **Step 4: Commit verification note (if needed)**

Message: `chore: verify app-level AI config — pytest + eval green`

---

## Verification Checklist (Stage Gate)

- [ ] `config/app.yaml` exists, contains cmdc/minimax verbatim migrated from `docs/domain/3gpp/config.yaml`, `api_key: null`, `api_key_env: COMMAND_CODE_API_KEY`, no secret value in diff
- [ ] `docs/domain/3gpp/config.yaml` and `_template/config.yaml` no longer contain `llm:`/`embed:` (or they are deprecated with warning)
- [ ] `LLMConfig.api_key_env` + `_resolve_api_key` respects declarative wiring: cmdc→COMMAND_CODE_API_KEY, openai→OPENAI_API_KEY, ollama→None (covered by `tests/test_app_config.py`)
- [ ] CLI `--app-config` works; default `config/app.yaml` auto-discovery works; `--help` documents it
- [ ] `pytest -q` green; `git diff` shows no secret; `.env` still ignored
- [ ] Docs updated: ADR-0015, architecture §3.1.1, roadmap/status reflect app-level config

## Roll-back Plan

Revert the 4 commits in reverse order (Task 4 docs → Task 3 domain packs → Task 2 CLI → Task 1 schema). Domain packs retain `llm`/`embed` fallback with warning, so reverting app config alone restores old behavior without data loss.

