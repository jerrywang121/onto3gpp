"""Tests for the web interface (FastAPI app + endpoints)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from onto3gpp.compile.dictionary import build_dictionary
from onto3gpp.extract.terms import CandidateTerm
from onto3gpp.ontology.schema import Concept, Ontology, Relation
from onto3gpp.web.app import create_app


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def _write_data(tmp_path: Path):
    """Write a small parsed corpus, dictionary, and ontology to tmp_path."""
    parsed = tmp_path / "parsed"
    parsed.mkdir()
    chunks = [
        {
            "spec": "38300",
            "release": "Rel-18",
            "clause": "6.1",
            "title": "SMF",
            "text": (
                "The Session Management Function (SMF) is responsible for "
                "session management and selection of the user plane function (UPF)."
            ),
        },
        {
            "spec": "38300",
            "release": "Rel-18",
            "clause": "6.2",
            "title": "QoS Flow",
            "text": "A QoS flow is the finest granularity of QoS forwarding treatment.",
        },
    ]
    with (parsed / "38300.jsonl").open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")

    dict_path = tmp_path / "dict.json"
    terms = [
        _term("SMF", abbreviations=["Session Management Function"]),
        _term("UPF"),
        _term("PDU Session", type="phrase"),
    ]
    dict_path.write_text(
        json.dumps(build_dictionary(terms).to_dict()), encoding="utf-8"
    )

    onto_path = tmp_path / "ontology.json"
    onto = Ontology(
        concepts=[
            Concept(id="smf", canonical="SMF", aliases=["Session Management Function"]),
            Concept(id="upf", canonical="UPF"),
            Concept(id="pdu_session", canonical="PDU Session"),
            Concept(id="qos_flow", canonical="QoS Flow"),
        ],
        relations=[
            Relation(source="smf", rel="selects", target="upf"),
            Relation(source="smf", rel="establishes", target="pdu_session"),
        ],
    )
    from onto3gpp.ontology.schema import ontology_to_dict

    onto_path.write_text(json.dumps(ontology_to_dict(onto)), encoding="utf-8")
    return parsed, dict_path, onto_path


@pytest.fixture()
def client(tmp_path):
    parsed, dict_path, onto_path = _write_data(tmp_path)
    app = create_app(parsed, dict_path=dict_path, ontology_path=onto_path)
    return TestClient(app)


def test_meta_endpoint(client):
    res = client.get("/api/meta")
    assert res.status_code == 200
    data = res.json()
    assert data["chunks"] == 2
    assert data["concepts"] == 4
    assert data["relations"] == 2


def test_query_endpoint_returns_ranked_results(client):
    res = client.post("/api/query", json={"query": "SMF", "top_k": 5})
    assert res.status_code == 200
    data = res.json()
    assert data["query"] == "SMF"
    assert len(data["results"]) > 0
    # results are ranked with a score
    assert data["results"][0]["score"] >= data["results"][-1]["score"]
    # plan includes the resolved concept
    assert "SMF" in data["plan"]["primary_terms"]


def test_query_endpoint_empty_query_returns_400(client):
    res = client.post("/api/query", json={"query": ""})
    assert res.status_code == 400


def test_query_endpoint_respects_top_k(client):
    res = client.post("/api/query", json={"query": "SMF", "top_k": 1})
    assert res.status_code == 200
    assert len(res.json()["results"]) <= 1


def test_query_endpoint_max_hops_expands_related(client):
    # With max_hops=2, the reasoner reaches 2-hop neighbors. Here SMF's
    # neighbors are UPF and PDU Session; the plan should include them.
    res = client.post("/api/query", json={"query": "SMF", "max_hops": 2})
    assert res.status_code == 200
    related = res.json()["plan"]["related_terms"]
    assert "UPF" in related


def test_concepts_endpoint_filters_by_text(client):
    res = client.get("/api/concepts", params={"q": "smf"})
    assert res.status_code == 200
    data = res.json()
    assert len(data["concepts"]) == 1
    assert data["concepts"][0]["canonical"] == "SMF"


def test_concepts_endpoint_filters_by_type(client):
    res = client.get("/api/concepts", params={"type": "abbreviation"})
    assert res.status_code == 200
    data = res.json()
    assert all(c["type"] == "abbreviation" for c in data["concepts"])


def test_graph_endpoint_returns_neighborhood(client):
    res = client.get("/api/graph", params={"concept": "SMF", "radius": 1})
    assert res.status_code == 200
    data = res.json()
    assert data["center"] == "smf"
    # SMF's 1-hop neighbors: UPF, PDU Session
    canonicals = {n["canonical"] for n in data["nodes"]}
    assert "SMF" in canonicals
    assert "UPF" in canonicals
    assert "PDU Session" in canonicals
    assert len(data["edges"]) >= 2


def test_graph_endpoint_unknown_concept_returns_404(client):
    res = client.get("/api/graph", params={"concept": "does-not-exist"})
    assert res.status_code == 404


def test_index_serves_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "onto3gpp" in res.text
