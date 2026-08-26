# TBox Split Design

**Date:** 2026-08-26
**Status:** Approved
**Branch:** `stage/9-ai-ingestion`

## Motivation

The TBox (schema level: `concept_types`, `relation_types`,
`relation_type_constraints`) is the part of the domain pack most likely to
evolve independently — via `evolve_tbox` during ingestion. Today it is buried
inside `config.yaml` alongside unrelated runtime config (`intents`,
`intent_patterns`, `document_metadata`, `judge_threshold`, `llm`).

Investigation showed the current evolution loopback is **broken**: the `ingest`
command writes the evolved TBox to a per-run `.abox.tbox.json` side artifact
that **nothing reads back**. Each run re-derives the TBox from `config.yaml`
and evolves it fresh, so evolved types are lost between runs.

This change splits the TBox into a dedicated `tbox.yaml` and makes it the
**durable source of truth** that evolution writes back to — turning the
currently-dead loopback into a real one.

## Approach (Option A — `tbox.yaml` as source of truth)

### 1. New file — `docs/domain/<domain>/tbox.yaml`

Contains exactly the three TBox keys, moved verbatim from `config.yaml`:

```yaml
concept_types:
  - network_function
  - procedure
  - information_element
  - interface
  - protocol
  - qos
  - architecture
  - security

relation_types:
  - is_a
  - part_of
  - uses
  - selects
  - participates_in
  - specified_in
  - related_to

relation_type_constraints:
  - {source_type: network_function, rel: uses, target_type: network_function}
  - {source_type: network_function, rel: selects, target_type: network_function}
  # ... all 20 edges
```

### 2. `config.yaml` — drops the three TBox keys

Keeps `domain`, `intents`, `intent_patterns`, `document_metadata`,
`judge_threshold`, `llm`.

### 3. `src/onto3gpp/config.py`

- **Remove** `concept_types`, `relation_types`, `relation_type_constraints`
  fields from `DomainConfig`.
- **Remove** the `tbox()` method.
- **Add** a standalone `load_tbox(domain_dir: Path) -> TBox` that reads
  `tbox.yaml` and builds a `TBox` via `tbox_from_dict` (reusing the existing
  serializer). Raises `FileNotFoundError` if missing.
- `load_domain` unchanged (still reads `config.yaml`).

### 4. `src/onto3gpp/cli.py`

- `align` (line 423): `cfg.tbox()` → `load_tbox(domain)`.
- `ingest` (line 508): `cfg.tbox()` → `load_tbox(domain)`.
- `ingest` write-back (lines 549-550): **replace** the `.abox.tbox.json` write
  with a write back to `tbox.yaml`:

  ```python
  tbox_yaml = domain / "tbox.yaml"
  tbox_yaml.write_text(
      yaml.safe_dump(tbox_to_dict(result.tbox), sort_keys=False),
      encoding="utf-8",
  )
  click.echo(f"Wrote evolved TBox to {tbox_yaml}")
  ```

  This makes evolution **durable** — the next `ingest` run starts from the
  evolved schema. The dead `.abox.tbox.json` artifact is removed.

### 5. `docs/domain/_template/`

Add a `tbox.yaml` template (mirroring the current `_template` config.yaml TBox
block) so new domains get both files. Update `_template/README.md` structure
listing.

### 6. Tests

- `test_smoke.py`: `test_load_domain_pack` drops the `concept_types`
  assertion; `test_domain_pack_tbox` uses `load_tbox(domain_dir)` instead of
  `cfg.tbox()`.
- `test_cli_ingest.py`: change the `.abox.tbox.json` existence assertion to
  assert `tbox.yaml` was written back (and contains the evolved type).
- **New** `test_tbox_split.py`: round-trip — `load_tbox` reads a `tbox.yaml`,
  `tbox_to_dict` + `yaml.safe_dump` writes it back, `load_tbox` re-reads it
  equal.

### 7. Docs

- `docs/domain/3gpp/README.md`: document the split, show `tbox.yaml`.
- `docs/architecture.md` / `docs/status.md`: update the "curated in
  config.yaml / tbox.json" references to reflect `tbox.yaml` as the durable
  source of truth.

## Decision Points Resolved

- **Write-back target:** `tbox.yaml` (Option A) — evolution now genuinely
  loops back.
- **`.abox.tbox.json`:** removed (dead artifact).
- **Backward compat:** `DomainConfig` loses the three fields; all callers
  updated in the same change, so no compat shim needed.
