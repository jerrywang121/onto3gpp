"""Domain auto-detection (Stage 9).

Deterministic keyword-based detection: given a document's text and a map of
domain → keyword list, return the domain with the most keyword hits. This is
the deterministic-first path; an LLM classifier can be added later (ADR-0011).
"""

from __future__ import annotations


def detect_domain(text: str, domains: dict[str, list[str]]) -> str | None:
    """Return the domain whose keywords appear most in ``text``.

    ``domains`` maps a domain name to a list of keywords. Matching is
    case-insensitive substring matching. Returns the domain with the most hits,
    or ``None`` if no domain has any hit. Ties keep the first domain in dict
    order.
    """
    lower = text.lower()
    best_domain: str | None = None
    best_count = 0
    for domain, keywords in domains.items():
        count = sum(1 for kw in keywords if kw.lower() in lower)
        if count > best_count:
            best_count = count
            best_domain = domain
    return best_domain
