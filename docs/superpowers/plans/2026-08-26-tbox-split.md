# TBox Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the TBox (`concept_types`, `relation_types`, `relation_type_constraints`) out of `config.yaml` into a dedicated `tbox.yaml`, and make `tbox.yaml` the durable source of truth that the `ingest` command writes the evolved TBox back to.

**Architecture:** Add a standalone `load_tbox(domain_dir)` in `config.py` that reads `tbox.yaml` and builds a `TBox` via the existing `tbox_from_dict`. Remove the three TBox fields from `DomainConfig` and its `tbox()` method. Update the `align` and `ingest` CLI commands to use `load_tbox`, and change `ingest`'s write-back from the dead `.abox.tbox.json` artifact to `tbox.yaml`. Add a `tbox.yaml` template to `_template` and update docs.

**Tech Stack:** Python 3.11, PyYAML, click, pytest.

## Global Constraints

- Python 3.11.14; venv at `.venv` — run tests with `.venv/bin/python -m pytest -o addopts="" -q`.
- `tbox.yaml` must contain exactly the three keys `concept_types`, `relation_types`, `relation_type_constraints` (moved verbatim from `config.yaml`).
- `config.yaml` keeps `domain`, `intents`, `intent_patterns`, `document_metadata`, `judge_threshold`, `llm` — and drops the three TBox keys.
- `load_tbox(domain_dir)` raises `FileNotFoundError` if `tbox.yaml` is missing (mirroring `load_domain`).
- Reuse `tbox_to_dict` / `tbox_from_dict` from `onto3gpp.ontology.tbox` for serialization — do not hand-roll.
- The `.abox.tbox.json` side artifact is removed; `ingest` writes the evolved TBox back to `tbox.yaml` instead.
- No backward-compat shim: all callers of `cfg.tbox()` / the removed fields are updated in the same change.

---

### Task 1: Add `load_tbox` and remove TBox from `DomainConfig`

**Files:**
- Modify: `src/onto3gpp/config.py`
- Test: `tests/test_smoke.py`

**Interfaces:**
- Consumes: `TBox`, `tbox_from_dict` from `onto3gpp.ontology.tbox`; `yaml` (already imported).
- Produces: `load_tbox(domain_dir: Path) -> TBox` — reads `tbox.yaml`, returns a `TBox`. Raises `FileNotFoundError` if missing. Later tasks call this.

- [ ] **Step 1: Write the failing test**

Update `tests/test_smoke.py` so `test_load_domain_pack` no longer asserts on `cfg.concept_types`, and `test_domain_pack_tbox` uses `load_tbox`:

```python
from onto3gpp.config import load_domain, load_tbox


def test_load_domain_pack() -> None:
    """The 3gpp domain pack should load without error."""
    domain_dir = Path(__file__).resolve().parents[1] / "docs" / "domain" / "3gpp"
    cfg = load_domain(domain_dir)
    assert cfg.domain == "3gpp"
    assert cfg.judge_threshold == 0.8


def test_domain_pack_tbox() -> None:
    """The 3gpp domain pack should build a TBox with constraints."""
    domain_dir = Path(__file__).resolve().parents[1] / "docs" / "domain" / "3gpp"
    tbox = load_tbox(domain_dir)
    assert tbox.is_known_concept_type("network_function")
    assert tbox.is_known_relation_type("selects")
    assert tbox.allows("network_function", "selects", "network_function")
    assert not tbox.allows("network_function", "selects", "procedure")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" tests/test_smoke.py -q`
Expected: FAIL — `ImportError: cannot import name 'load_tbox'` (and `tbox.yaml` does not exist yet).

- [ ] **Step 3: Write minimal implementation**

In `src/onto3gpp/config.py`:

Remove the three fields from `DomainConfig` and the `tbox()` method:

```python
@dataclass
class DomainConfig:
    """Configuration loaded from a domain pack's config.yaml."""

    domain: str
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
```

Remove the now-unused `TBox` import at the top of the file (keep `from onto3gpp.ontology.tbox import TBox` only if still referenced — it is not after removing `tbox()`).

Add `load_tbox` after `load_domain`:

```python
def load_tbox(domain_dir: Path) -> TBox:
    """Load the TBox from a domain pack's tbox.yaml."""
    from onto3gpp.ontology.tbox import tbox_from_dict

    tbox_path = domain_dir / "tbox.yaml"
    if not tbox_path.exists():
        raise FileNotFoundError(f"No tbox.yaml in domain pack: {domain_dir}")
    data = yaml.safe_load(tbox_path.read_text())
    return tbox_from_dict(data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -o addopts="" tests/test_smoke.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/onto3gpp/config.py tests/test_smoke.py
git commit -m "refactor(config): split TBox into load_tbox(domain_dir)"
```

---

### Task 2: Create `tbox.yaml` for 3gpp and strip TBox from `config.yaml`

**Files:**
- Create: `docs/domain/3gpp/tbox.yaml`
- Modify: `docs/domain/3gpp/config.yaml`

**Interfaces:**
- Consumes: nothing new.
- Produces: `docs/domain/3gpp/tbox.yaml` — the file `load_tbox` reads. `config.yaml` no longer contains the three TBox keys.

- [ ] **Step 1: Create `docs/domain/3gpp/tbox.yaml`**

```yaml
# Top-level ontology (TBox) — the blueprint / constraint for the ABox.
# concept_types are the TBox nodes; relation_type_constraints are the TBox
# edges (which relation types may connect which concept types). Curated here
# by default; AI may evolve it only when evidence demands (ADR-0010, ADR-0011).
# The `ingest` command writes the evolved TBox back to this file.
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

# TBox edges: (source_type, rel, target_type). A relation in the ABox is valid
# only if its (source.type, rel, target.type) appears here.
relation_type_constraints:
  - {source_type: network_function, rel: uses, target_type: network_function}
  - {source_type: network_function, rel: selects, target_type: network_function}
  - {source_type: network_function, rel: participates_in, target_type: procedure}
  - {source_type: network_function, rel: uses, target_type: procedure}
  - {source_type: procedure, rel: uses, target_type: network_function}
  - {source_type: procedure, rel: uses, target_type: information_element}
  - {source_type: procedure, rel: part_of, target_type: procedure}
  - {source_type: information_element, rel: part_of, target_type: information_element}
  - {source_type: interface, rel: connects, target_type: network_function}
  - {source_type: protocol, rel: uses, target_type: interface}
  - {source_type: qos, rel: part_of, target_type: procedure}
  - {source_type: architecture, rel: part_of, target_type: architecture}
  - {source_type: security, rel: uses, target_type: procedure}
  - {source_type: network_function, rel: is_a, target_type: network_function}
  - {source_type: procedure, rel: is_a, target_type: procedure}
  - {source_type: information_element, rel: is_a, target_type: information_element}
  - {source_type: network_function, rel: specified_in, target_type: architecture}
  - {source_type: procedure, rel: specified_in, target_type: architecture}
  - {source_type: network_function, rel: related_to, target_type: network_function}
  - {source_type: procedure, rel: related_to, target_type: procedure}
```

- [ ] **Step 2: Strip the TBox block from `docs/domain/3gpp/config.yaml`**

Remove the entire block from the `# Top-level ontology (TBox)` comment through the last `relation_type_constraints` entry (the 20 edges), leaving `domain: 3gpp` followed directly by `intents:`. The result starts:

```yaml
domain: 3gpp

intents:
  - DEFINITION
```

- [ ] **Step 3: Run the smoke tests**

Run: `.venv/bin/python -m pytest -o addopts="" tests/test_smoke.py -q`
Expected: PASS — `load_tbox` now reads the real `tbox.yaml`.

- [ ] **Step 4: Commit**

```bash
git add docs/domain/3gpp/tbox.yaml docs/domain/3gpp/config.yaml
git commit -m "feat(domain): split 3gpp TBox into tbox.yaml"
```

---

### Task 3: Update CLI `align` and `ingest` to use `load_tbox`; write evolved TBox back to `tbox.yaml`

**Files:**
- Modify: `src/onto3gpp/cli.py`
- Test: `tests/test_cli_ingest.py`

**Interfaces:**
- Consumes: `load_tbox` from `onto3gpp.config` (Task 1); `tbox_to_dict` from `onto3gpp.ontology.tbox` (already imported in `ingest`); `yaml`.
- Produces: `align` and `ingest` commands load the TBox from `tbox.yaml`; `ingest` writes the evolved TBox back to `tbox.yaml` and no longer writes `.abox.tbox.json`.

- [ ] **Step 1: Write the failing test**

Update `tests/test_cli_ingest.py` to assert the evolved TBox is written back to `tbox.yaml` (and no longer to `.abox.tbox.json`):

```python
"""Tests for the CLI ingest command (Stage 9)."""

import json

from click.testing import CliRunner

from onto3gpp.cli import main


def test_ingest_command_writes_abox_and_tbox(tmp_path):
    parsed = tmp_path / "doc.jsonl"
    parsed.write_text(
        json.dumps(
            {
                "spec": "23.501",
                "release": "Rel-18",
                "clause": "5.6.1",
                "title": "PDU Session",
                "text": "The SMF establishes the PDU session.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", "--parsed", str(parsed)])
    assert result.exit_code == 0, result.output
    assert "Wrote ABox" in result.output
    assert "Wrote evolved TBox" in result.output
    assert parsed.with_suffix(".abox.json").exists()
    assert not parsed.with_suffix(".abox.tbox.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" tests/test_cli_ingest.py -q`
Expected: FAIL — `"Wrote evolved TBox" not in result.output` and `.abox.tbox.json` still exists.

- [ ] **Step 3: Write minimal implementation**

In `src/onto3gpp/cli.py`:

In the `align` command (around line 423), change:

```python
    cfg = load_domain(domain)
    tbox = cfg.tbox()
```

to:

```python
    from onto3gpp.config import load_tbox

    cfg = load_domain(domain)
    tbox = load_tbox(domain)
```

In the `ingest` command (around line 508), change:

```python
    cfg = load_domain(domain)
    tbox = cfg.tbox()
```

to:

```python
    from onto3gpp.config import load_tbox

    cfg = load_domain(domain)
    tbox = load_tbox(domain)
```

In the `ingest` command, replace the `.abox.tbox.json` write-back (around lines 549-550):

```python
    tbox_out = out.with_suffix(".tbox.json")
    tbox_out.write_text(json.dumps(tbox_to_dict(result.tbox), indent=2), encoding="utf-8")
    click.echo(f"Wrote TBox to {tbox_out}")
```

with a write back to `tbox.yaml`:

```python
    import yaml

    tbox_yaml = domain / "tbox.yaml"
    tbox_yaml.write_text(
        yaml.safe_dump(tbox_to_dict(result.tbox), sort_keys=False),
        encoding="utf-8",
    )
    click.echo(f"Wrote evolved TBox to {tbox_yaml}")
```

Note: `tbox_to_dict` is already imported inside `ingest` (line 502). If `json` is no longer used for the TBox write, leave the existing `import json` (it is still used for the ABox write).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest -o addopts="" tests/test_cli_ingest.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -o addopts="" -q`
Expected: PASS (all tests, including `test_smoke.py`).

- [ ] **Step 6: Commit**

```bash
git add src/onto3gpp/cli.py tests/test_cli_ingest.py
git commit -m "feat(cli): write evolved TBox back to tbox.yaml"
```

---

### Task 4: Add `tbox.yaml` template to `_template` and update `_template/README.md`

**Files:**
- Create: `docs/domain/_template/tbox.yaml`
- Modify: `docs/domain/_template/README.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a `tbox.yaml` template so new domains get both files; README documents the split.

- [ ] **Step 1: Create `docs/domain/_template/tbox.yaml`**

```yaml
# Top-level ontology (TBox) — the blueprint / constraint for the ABox.
# concept_types are the TBox nodes; relation_type_constraints are the TBox
# edges (which relation types may connect which concept types). Curated here
# by default; AI may evolve it only when evidence demands (ADR-0010, ADR-0011).
# The `ingest` command writes the evolved TBox back to this file.
concept_types:
  - concept
  - procedure
  - entity
  - interface

relation_types:
  - is_a
  - part_of
  - uses
  - related_to

# TBox edges: (source_type, rel, target_type). A relation in the ABox is valid
# only if its (source.type, rel, target.type) appears here. This is the
# top-level ontology graph (TBox) that constrains the low-level knowledge
# graph (ABox). See ADR-0010.
relation_type_constraints:
  - {source_type: concept, rel: is_a, target_type: concept}
  - {source_type: procedure, rel: uses, target_type: entity}
  - {source_type: entity, rel: part_of, target_type: entity}
```

- [ ] **Step 2: Update `docs/domain/_template/README.md`**

Update the Structure block to include `tbox.yaml`:

```markdown
docs/domain/<domain>/
├── prompts/            # AI prompt templates (parameterized)
│   ├── extract_terms.txt
│   ├── extract_relations.txt
│   ├── judge_candidates.txt
│   └── propose_improvements.txt
├── config.yaml         # domain config (intents, patterns, metadata, llm)
└── tbox.yaml           # top-level ontology (TBox): concept/relation types + constraints
```

Remove the `concept_types`, `relation_types`, and `relation_type_constraints` blocks from the `config.yaml` example in the README (they now live in `tbox.yaml`). Add a `## tbox.yaml` section showing the template content above.

- [ ] **Step 3: Commit**

```bash
git add docs/domain/_template/tbox.yaml docs/domain/_template/README.md
git commit -m "feat(domain): add tbox.yaml template"
```

---

### Task 5: Update 3gpp README and architecture/status docs

**Files:**
- Modify: `docs/domain/3gpp/README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/status.md`

**Interfaces:**
- Consumes: nothing.
- Produces: docs reflect `tbox.yaml` as the durable source of truth.

- [ ] **Step 1: Update `docs/domain/3gpp/README.md`**

Replace the `## config.yaml` section's TBox block (the `concept_types` / `relation_types` / `relation_type_constraints` YAML) with a note that the TBox now lives in `tbox.yaml`, and add a `## tbox.yaml` section showing the file. Keep the `intents` / `document_metadata` / `judge_threshold` / `llm` parts in the `config.yaml` section.

- [ ] **Step 2: Update `docs/architecture.md`**

- Line 205-208 (domain pack tree): add `tbox.yaml` to the `_template` and `3gpp` listings.
- Line 305: change "The TBox is serialized as `tbox.json` (or embedded in the domain pack)." to "The TBox is serialized as `tbox.yaml` in the domain pack, and the `ingest` command writes the evolved TBox back to it."

- [ ] **Step 3: Update `docs/status.md`**

- Line 388-389: change "`DomainConfig.relation_type_constraints` + `DomainConfig.tbox()` — builds the TBox from the domain pack `config.yaml`." to "`load_tbox(domain_dir)` — loads the TBox from the domain pack `tbox.yaml`."

- [ ] **Step 4: Commit**

```bash
git add docs/domain/3gpp/README.md docs/architecture.md docs/status.md
git commit -m "docs: document tbox.yaml as the TBox source of truth"
```

---

### Task 6: Add round-trip test for `tbox.yaml` write-back

**Files:**
- Create: `tests/test_tbox_split.py`

**Interfaces:**
- Consumes: `load_tbox` from `onto3gpp.config`; `tbox_to_dict` from `onto3gpp.ontology.tbox`; `yaml`.
- Produces: a test proving a `tbox.yaml` written via `yaml.safe_dump(tbox_to_dict(...))` round-trips through `load_tbox` unchanged.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the TBox split (tbox.yaml as source of truth)."""

from pathlib import Path

import yaml

from onto3gpp.config import load_tbox
from onto3gpp.ontology.tbox import tbox_to_dict


def test_tbox_yaml_roundtrip(tmp_path):
    """A tbox.yaml written via tbox_to_dict + safe_dump round-trips."""
    domain_dir = tmp_path / "domain"
    domain_dir.mkdir()
    tbox_yaml = domain_dir / "tbox.yaml"
    tbox_yaml.write_text(
        yaml.safe_dump(
            {
                "concept_types": ["network_function", "procedure"],
                "relation_types": ["uses", "part_of"],
                "relation_type_constraints": [
                    {"source_type": "network_function", "rel": "uses", "target_type": "procedure"}
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    tbox = load_tbox(domain_dir)
    assert tbox.is_known_concept_type("network_function")
    assert tbox.is_known_relation_type("uses")
    assert tbox.allows("network_function", "uses", "procedure")

    # Write back and re-read — must be equal.
    tbox_yaml.write_text(
        yaml.safe_dump(tbox_to_dict(tbox), sort_keys=False),
        encoding="utf-8",
    )
    assert load_tbox(domain_dir) == tbox


def test_load_tbox_missing_raises(tmp_path):
    """load_tbox raises FileNotFoundError when tbox.yaml is absent."""
    import pytest

    with pytest.raises(FileNotFoundError):
        load_tbox(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest -o addopts="" tests/test_tbox_split.py -q`
Expected: FAIL — `ImportError: cannot import name 'load_tbox'` (if Task 1 not yet merged) or PASS (if it is). If it passes, that is fine — the test is the deliverable; run the full suite to confirm no regressions.

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest -o addopts="" -q`
Expected: PASS (all tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_tbox_split.py
git commit -m "test: tbox.yaml round-trip via load_tbox"
```
