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
