"""Tests for domain auto-detection (Stage 9)."""

from onto3gpp.ingest.detect import detect_domain


def test_detect_domain_by_keyword():
    domains = {
        "3gpp": ["3gpp", "5g", "nr", "pdu session", "network function"],
        "etsi": ["etsi", "nfv", "vim"],
    }
    text = "This 3GPP specification describes the 5G NR PDU session."
    assert detect_domain(text, domains) == "3gpp"


def test_detect_domain_returns_none_when_no_match():
    domains = {"3gpp": ["3gpp", "5g"], "etsi": ["etsi", "nfv"]}
    text = "A generic document about cooking."
    assert detect_domain(text, domains) is None


def test_detect_domain_case_insensitive():
    domains = {"3gpp": ["pdu session"]}
    text = "The PDU Session is established."
    assert detect_domain(text, domains) == "3gpp"


def test_detect_domain_ties_keep_first():
    domains = {"a": ["x"], "b": ["x"]}
    text = "x"
    assert detect_domain(text, domains) == "a"
