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
    assert "Wrote TBox" in result.output
    assert parsed.with_suffix(".abox.json").exists()
    assert parsed.with_suffix(".abox.tbox.json").exists()
