"""Tests for search-log collection + offline analysis (Stage 4)."""

from __future__ import annotations

import json
from pathlib import Path

from onto3gpp.improve.logs import (
    SearchLog,
    analyze_logs,
    collect_logs,
    load_logs,
    record_log,
)


def test_record_and_load_logs_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "search_logs.jsonl"
    record_log(
        path,
        SearchLog(
            query="How is handover handled?",
            top_clauses=["16.15.5", "9.3.4.1"],
            clicked_clause="9.2.3.2",
        ),
    )
    logs = load_logs(path)
    assert len(logs) == 1
    assert logs[0].query == "How is handover handled?"
    assert logs[0].clicked_clause == "9.2.3.2"


def test_collect_logs_from_gold(tmp_path: Path) -> None:
    """Collect search logs by running a gold set through an index."""
    from onto3gpp.evaluate import GoldQuery
    from onto3gpp.search.bm25 import BM25Index
    from onto3gpp.search.chunker import Chunk

    chunks = [
        Chunk(spec="38.300", release="Rel-18", clause="9.2.3.2", title="", text="The handover procedure is performed by the gNB during RRC_CONNECTED."),
        Chunk(spec="38.300", release="Rel-18", clause="16.15.5", title="", text="The PDU set based handling is supported for the QoS flow."),
        Chunk(spec="38.300", release="Rel-18", clause="9.3.4.1", title="", text="The SRVCC operation is used for voice continuity."),
        Chunk(spec="38.300", release="Rel-18", clause="13.3", title="", text="State transitions and mobility are handled by the RRC layer."),
    ]
    index = BM25Index.build(chunks)
    gold = [GoldQuery(query="handover", relevant_clauses=["9.2.3.2"])]
    path = tmp_path / "logs.jsonl"
    collect_logs(index, gold, path)
    logs = load_logs(path)
    assert len(logs) == 1
    assert logs[0].query == "handover"
    assert logs[0].clicked_clause == "9.2.3.2"


def test_analyze_logs_finds_missed_terms() -> None:
    """A query token absent from the ontology is a 'missed term' finding."""
    from onto3gpp.ontology.schema import Concept, Ontology

    onto = Ontology(concepts=[Concept(id="handover", canonical="handover")])
    logs = [
        SearchLog(
            query="handover in RRC_CONNECTED",
            top_clauses=["9.2.3.2"],
            clicked_clause="9.2.3.2",
        )
    ]
    findings = analyze_logs(logs, onto)
    # "rrc_connected" is not a concept → missed term
    assert any("rrc_connected" in f for f in findings["missed_terms"])


def test_analyze_logs_finds_mismatch() -> None:
    """A clicked clause absent from the top results is a 'mismatch' finding."""
    from onto3gpp.ontology.schema import Concept, Ontology

    onto = Ontology(concepts=[Concept(id="handover", canonical="handover")])
    logs = [
        SearchLog(
            query="handover",
            top_clauses=["16.15.5", "9.3.4.1"],
            clicked_clause="9.2.3.2",
        )
    ]
    findings = analyze_logs(logs, onto)
    assert "9.2.3.2" in findings["mismatches"]


def test_analyze_logs_finds_cooccurrences() -> None:
    """Terms that co-occur in queries are surfaced as co-occurrence findings."""
    from onto3gpp.ontology.schema import Concept, Ontology

    onto = Ontology(concepts=[Concept(id="handover", canonical="handover")])
    logs = [
        SearchLog(query="handover RRC_CONNECTED", top_clauses=["9.2.3.2"], clicked_clause="9.2.3.2"),
        SearchLog(query="handover RRC_CONNECTED", top_clauses=["9.2.3.2"], clicked_clause="9.2.3.2"),
    ]
    findings = analyze_logs(logs, onto)
    assert any("handover" in c and "rrc_connected" in c for c in findings["cooccurrences"])
