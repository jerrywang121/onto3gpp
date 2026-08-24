"""Intent detector (Stage 3).

Deterministic, CPU-only query-intent classification. Given a query, classify
it into one of the domain's intent types (e.g. DEFINITION, PROCEDURE,
SECURITY) using pattern matching. The patterns are domain-agnostic by default
but can be overridden by a domain pack's config.

The intent is used downstream to apply intent-specific structure boosts (e.g.
a PROCEDURE query boosts procedure clauses; a SECURITY query boosts security
clauses).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Default intent patterns. Each intent maps to a list of regexes; a query
# matches an intent if any of its regexes matches (case-insensitive). These
# are generic English patterns that work across domains; a domain pack can
# supply its own via config.yaml `intent_patterns`.
DEFAULT_INTENT_PATTERNS: dict[str, list[str]] = {
    "DEFINITION": [
        r"\bwhat is\b",
        r"\bwhat are\b",
        r"\bdefine\b",
        r"\bdefinition of\b",
        r"\bmeaning of\b",
        r"\bis defined as\b",
    ],
    "PURPOSE": [
        r"\bwhat is the purpose\b",
        r"\bwhat is the role\b",
        r"\bwhy\b",
        r"\bfor what\b",
        r"\bintended for\b",
    ],
    "PROCEDURE": [
        r"\bhow does\b",
        r"\bhow is\b",
        r"\bhow do\b",
        r"\bhow are\b",
        r"\bprocedure\b",
        r"\bprocess\b",
        r"\bperforms?\b",
        r"\bcarried out\b",
        r"\bsteps?\b",
    ],
    "MESSAGE_FLOW": [
        r"\bmessage flow\b",
        r"\bsignalling flow\b",
        r"\bsequence\b",
        r"\bexchange\b",
        r"\bflow\b",
    ],
    "CONFIGURATION": [
        r"\bconfigured\b",
        r"\bconfiguration\b",
        r"\bset up\b",
        r"\bsettings\b",
        r"\bparameters?\b",
    ],
    "PARAMETER": [
        r"\bparameter\b",
        r"\bvalue of\b",
        r"\bfield\b",
        r"\bIE\b",
        r"\binformation element\b",
    ],
    "FAILURE": [
        r"\bfail\b",
        r"\bfailure\b",
        r"\berror\b",
        r"\bbreak\b",
        r"\bnot working\b",
    ],
    "ERROR_HANDLING": [
        r"\berror handling\b",
        r"\bexception\b",
        r"\bwhen.*fails\b",
        r"\brecovery\b",
    ],
    "SECURITY": [
        r"\bsecurity\b",
        r"\bauthentication\b",
        r"\bauthorization\b",
        r"\bencryption\b",
        r"\bintegrity\b",
        r"\bprivacy\b",
        r"\bkey\b",
    ],
    "COMPARISON": [
        r"\bvs\b",
        r"\bversus\b",
        r"\bdifference between\b",
        r"\bcompare\b",
        r"\bcompared to\b",
    ],
    "DEPENDENCY": [
        r"\bdepend(s|ing)? on\b",
        r"\brequires?\b",
        r"\bneeds?\b",
        r"\brelies on\b",
        r"\bprerequisite\b",
    ],
    "ARCHITECTURE": [
        r"\barchitecture\b",
        r"\boverview\b",
        r"\bcomponents?\b",
        r"\bstructure\b",
        r"\bdeployment\b",
    ],
    "REQUIREMENT": [
        r"\brequirement\b",
        r"\bmust\b",
        r"\bshall\b",
        r"\brequired to\b",
        r"\bmandatory\b",
    ],
}


@dataclass
class IntentResult:
    """The detected intent of a query."""

    intent: str | None
    confidence: float
    matched_patterns: list[str] = None  # type: ignore[assignment]


def _compile(patterns: dict[str, list[str]]) -> dict[str, list[re.Pattern]]:
    """Compile a patterns dict into compiled regexes."""
    return {
        intent: [re.compile(p, re.IGNORECASE) for p in pats]
        for intent, pats in patterns.items()
    }


def detect_intent(
    query: str,
    patterns: dict[str, list[str]] | None = None,
) -> IntentResult:
    """Classify a query into an intent type.

    Returns an :class:`IntentResult` with the best-matching intent and a
    confidence score (the fraction of the query's matched patterns, or a
    simple 0-1 score). If no pattern matches, intent is ``None``.
    """
    if patterns is None:
        patterns = DEFAULT_INTENT_PATTERNS
    compiled = _compile(patterns)

    best_intent: str | None = None
    best_matches: list[str] = []
    best_count = 0
    best_pos = -1

    for intent, regexes in compiled.items():
        matches: list[str] = []
        max_pos = -1
        for p in regexes:
            m = p.search(query)
            if m:
                matches.append(p.pattern)
                max_pos = max(max_pos, m.end())
        if not matches:
            continue
        # Prefer the intent with the most matched patterns. On a tie, prefer
        # the intent whose match occurs latest in the query — question openers
        # ("what is", "how does") match early, while the content word that
        # actually determines the intent ("security", "handover") matches
        # later. This makes "What is the security principle?" classify as
        # SECURITY, not DEFINITION.
        if len(matches) > best_count or (
            len(matches) == best_count and max_pos > best_pos
        ):
            best_count = len(matches)
            best_intent = intent
            best_matches = matches
            best_pos = max_pos

    if best_intent is None:
        return IntentResult(intent=None, confidence=0.0, matched_patterns=[])

    # Confidence: 1.0 if a single strong pattern matched, else scale by the
    # number of matched patterns (capped at 1.0). This is a heuristic; the
    # exact value is not critical since it's only used to weight boosts.
    confidence = min(1.0, 0.5 + 0.25 * best_count)
    return IntentResult(
        intent=best_intent,
        confidence=confidence,
        matched_patterns=best_matches,
    )
