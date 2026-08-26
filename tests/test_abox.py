"""Tests for the ABox (low-level knowledge graph) schema (Stage 7)."""

from onto3gpp.ontology.abox import (
    ABox,
    ABoxConcept,
    ABoxRelation,
    abox_from_dict,
    abox_to_dict,
)


def _abox() -> ABox:
    return ABox(
        concepts=[
            ABoxConcept(
                id="smf",
                canonical="SMF",
                type="network_function",
                aliases=["SMF"],
                metadata={"spec": "23.501"},
            ),
            ABoxConcept(
                id="upf",
                canonical="UPF",
                type="network_function",
                aliases=["UPF"],
                metadata={"spec": "23.501"},
            ),
        ],
        relations=[
            ABoxRelation(
                source="smf",
                rel="selects",
                target="upf",
                weight=0.7,
                confidence=0.9,
                provenance={"spec": "23.501", "clause": "6.2"},
            )
        ],
    )


def test_abox_roundtrip():
    abox = _abox()
    data = abox_to_dict(abox)
    assert data["concepts"][0]["id"] == "smf"
    assert data["concepts"][0]["type"] == "network_function"
    assert data["concepts"][0]["metadata"] == {"spec": "23.501"}
    assert data["relations"][0]["rel"] == "selects"
    assert data["relations"][0]["provenance"] == {"spec": "23.501", "clause": "6.2"}
    restored = abox_from_dict(data)
    assert restored == abox


def test_abox_from_dict_defaults():
    abox = abox_from_dict({"concepts": [{"id": "x", "canonical": "X"}], "relations": []})
    assert abox.concepts[0].type == "concept"
    assert abox.concepts[0].metadata == {}
    assert abox.relations == []
