"""Tests for NER-chain integration into the search path (Stage 5)."""

from onto3gpp.compile.dictionary import build_dictionary
from onto3gpp.extract.terms import CandidateTerm
from onto3gpp.ontology.schema import Concept, Ontology, Relation
from onto3gpp.search.bm25 import BM25Index
from onto3gpp.search.chunker import Chunk


def _term(canonical: str, type: str = "abbreviation", **kw) -> CandidateTerm:
    return CandidateTerm(canonical=canonical, type=type, **kw)


def _dict():
    terms = [
        _term("SMF", abbreviations=["Session Management Function"]),
        _term("UPF"),
        _term("PDU Session", type="phrase"),
    ]
    return build_dictionary(terms)


def _onto():
    return Ontology(
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


def _chunks():
    return [
        Chunk(
            spec="38300",
            release="Rel-18",
            clause="6.1",
            title="SMF",
            text=(
                "The Session Management Function (SMF) is responsible for "
                "session management, IP address allocation and management, "
                "selection and control of the user plane function (UPF), and "
                "the establishment of PDU sessions for the user equipment."
            ),
        ),
        Chunk(
            spec="38300",
            release="Rel-18",
            clause="6.2",
            title="QoS Flow",
            text=(
                "A QoS flow is the finest granularity of QoS forwarding "
                "treatment in the 5G system. Each QoS flow is identified by a "
                "QoS flow identifier and is associated with a set of QoS "
                "parameters that define the forwarding treatment."
            ),
        ),
        Chunk(
            spec="38300",
            release="Rel-18",
            clause="6.3",
            title="Registration",
            text=(
                "The registration procedure is used by the user equipment to "
                "register with the network and obtain access to the services "
                "provided by the core network."
            ),
        ),
    ]


def test_search_chain_expands_with_fuzzy_match():
    index = BM25Index.build(_chunks())
    # "qos flow" is not in the dictionary, but the chain's fuzzy matcher (L2)
    # resolves it to the "QoS Flow" concept, expanding the query so the
    # relevant chunk (6.2) is retrieved.
    results = index.search_structure("qos flow", _onto(), dictionary=_dict(), top_k=5)
    clauses = {r.chunk.clause for r in results}
    assert "6.2" in clauses


def test_search_chain_expands_with_related_concepts():
    index = BM25Index.build(_chunks())
    # "SMF" resolves at L0; its 1-hop neighbor "UPF" is added at L4, so the
    # chunk mentioning UPF (6.1) is retrieved even though the query only says
    # SMF.
    results = index.search_structure("SMF", _onto(), dictionary=_dict(), top_k=5)
    clauses = {r.chunk.clause for r in results}
    assert "6.1" in clauses


def test_search_chain_empty_query_returns_empty():
    index = BM25Index.build(_chunks())
    results = index.search_structure("", _onto(), dictionary=_dict(), top_k=5)
    assert results == []
