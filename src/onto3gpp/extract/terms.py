"""Candidate term extraction (Stage 1).

Rules-based extraction of candidate ontology terms from parsed sections.
This is the deterministic, AI-free path. An optional LLM path can be added
later (see docs/domain/3gpp/prompts/extract_terms.txt).

Extraction rules:
- **Abbreviations**: all-caps tokens (e.g. SMF, UPF, AMF, DNN, S-NSSAI, QFI).
- **Phrases**: capitalized multi-word noun phrases from section titles
  (e.g. "PDU Session").
- **Linking**: an abbreviation immediately following a phrase in parentheses
  ("Session Management Function (SMF)") links the abbreviation to the phrase.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from onto3gpp.parser import Section

# All-caps token, possibly with hyphens/digits: SMF, UPF, S-NSSAI, QFI, NGAP
_ABBR_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*\b")
# "Phrase (ABBR)" — abbreviation in parens right after a capitalized phrase
_PAREN_ABBR_RE = re.compile(r"\(([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*)\)")
# A capitalized multi-word title phrase: "PDU Session", "QoS Flow Mapping"
_TITLE_PHRASE_RE = re.compile(
    r"\b[A-Z][a-zA-Z0-9-]*(?:\s+[A-Z][a-zA-Z0-9-]*)+"
)


@dataclass
class CandidateTerm:
    """A candidate ontology term extracted from source text."""

    canonical: str
    type: str  # "abbreviation" | "phrase"
    aliases: list[str] = field(default_factory=list)
    abbreviations: list[str] = field(default_factory=list)
    confidence: float = 0.5
    provenance: dict = field(default_factory=dict)


def _abbreviations(text: str) -> list[str]:
    """Return all-caps tokens that look like abbreviations."""
    return list(dict.fromkeys(_ABBR_RE.findall(text)))


# Words that should not start a phrase (articles, prepositions, conjunctions)
_STOP_START = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "by",
    "with", "from", "at", "as", "is", "are", "be", "that", "this", "each",
    "during", "between", "while", "how", "what", "which", "when",
}


def _strip_leading_stop(phrase: str) -> str:
    """Remove leading stop words from a phrase, e.g. "The PDU Session" → "PDU Session"."""
    words = phrase.split()
    while words and words[0].lower() in _STOP_START:
        words = words[1:]
    return " ".join(words)


def _phrases(text: str) -> list[str]:
    """Return capitalized multi-word noun phrases from a title."""
    return list(dict.fromkeys(_strip_leading_stop(p) for p in _TITLE_PHRASE_RE.findall(text)))


def _paren_phrases(text: str) -> list[str]:
    """Return capitalized phrases that immediately precede a parenthesized
    abbreviation, e.g. "Session Management Function (SMF)" → the phrase."""
    phrases: list[str] = []
    for m in _PAREN_ABBR_RE.finditer(text):
        before = text[: m.start()].rstrip()
        # find the longest trailing capitalized multi-word phrase
        match = _TITLE_PHRASE_RE.search(before)
        if match and before.endswith(match.group(0)):
            phrases.append(_strip_leading_stop(match.group(0)))
    return list(dict.fromkeys(phrases))


def _link_abbreviations(text: str, phrases: list[str]) -> dict[str, list[str]]:
    """Map each phrase to abbreviations that appear in parens after it.

    Returns {phrase: [abbr, ...]}.
    """
    links: dict[str, list[str]] = {}
    # Find "Phrase (ABBR)" patterns
    for m in _PAREN_ABBR_RE.finditer(text):
        abbr = m.group(1)
        # Look backwards from the paren for the nearest phrase ending
        before = text[: m.start()].rstrip()
        for phrase in phrases:
            if before.endswith(phrase):
                links.setdefault(phrase, []).append(abbr)
                break
    return links


def extract_candidates(sections: list[Section]) -> list[CandidateTerm]:
    """Extract candidate terms from a list of sections."""
    candidates: list[CandidateTerm] = []
    seen: dict[str, CandidateTerm] = {}

    for s in sections:
        text = s.text
        for abbr in _abbreviations(text):
            if abbr not in seen:
                seen[abbr] = CandidateTerm(
                    canonical=abbr,
                    type="abbreviation",
                    confidence=0.6,
                    provenance={"spec": s.spec, "clause": s.clause},
                )
        # Phrases come from the section title (clean noun phrases) plus any
        # phrase that precedes a parenthesized abbreviation in the body.
        phrases = _phrases(s.title) + _paren_phrases(text)
        links = _link_abbreviations(text, phrases)
        for phrase in phrases:
            if phrase not in seen:
                seen[phrase] = CandidateTerm(
                    canonical=phrase,
                    type="phrase",
                    confidence=0.5,
                    provenance={"spec": s.spec, "clause": s.clause},
                )
            # attach linked abbreviations
            for abbr in links.get(phrase, []):
                if abbr not in seen[phrase].abbreviations:
                    seen[phrase].abbreviations.append(abbr)

    return list(seen.values())
