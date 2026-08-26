"""Tests for the CLI ingest command (Stage 9)."""

import json

import yaml
from click.testing import CliRunner

from onto3gpp.cli import main


def _make_domain(tmp_path):
    """Create a minimal hermetic domain pack (config.yaml + tbox.yaml)."""
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "config.yaml").write_text(
        "domain: test\nintents:\n  - DEFINITION\n",
        encoding="utf-8",
    )
    (domain / "tbox.yaml").write_text(
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
    return domain


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
    domain = _make_domain(tmp_path)
    runner = CliRunner()
    result = runner.invoke(main, ["ingest", "--parsed", str(parsed), "--domain", str(domain)])
    assert result.exit_code == 0, result.output
    assert "Wrote ABox" in result.output
    assert "Wrote evolved TBox" in result.output
    assert parsed.with_suffix(".abox.json").exists()
    assert not parsed.with_suffix(".abox.tbox.json").exists()
    # The evolved TBox is written back to the domain pack's tbox.yaml.
    assert (domain / "tbox.yaml").exists()
