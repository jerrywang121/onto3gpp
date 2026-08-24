"""Tests for the intent detector (Stage 3)."""

from onto3gpp.runtime.intent import IntentResult, detect_intent


def test_detect_procedure_intent():
    result = detect_intent("How does a UE perform cell reselection?")
    assert isinstance(result, IntentResult)
    assert result.intent == "PROCEDURE"
    assert result.confidence > 0.0


def test_detect_definition_intent():
    result = detect_intent("What is the RAN-based notification area?")
    assert result.intent == "DEFINITION"


def test_detect_security_intent():
    result = detect_intent("What are the security principles for NR?")
    assert result.intent == "SECURITY"


def test_detect_unknown_intent_returns_none():
    result = detect_intent("gibberish query without any pattern")
    assert result.intent is None
    assert result.confidence == 0.0


def test_detect_intent_accepts_domain_config():
    # A custom domain pack can supply its own intent patterns.
    patterns = {
        "FAILURE": [r"\b(fail|failure|error|break)\b"],
    }
    result = detect_intent("What happens on failure?", patterns=patterns)
    assert result.intent == "FAILURE"
