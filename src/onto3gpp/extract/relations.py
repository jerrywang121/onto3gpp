"""Relation extraction (Stage 2).

Rules-based extraction of typed relations between known ontology concepts.
For each sentence, find known concepts (via the compiled dictionary) and
detect verbs that map to relation types. This is the deterministic, AI-free
path; an LLM path can be added later (see extract_relations.txt).

Verb → relation-type mapping is domain-agnostic (common English verbs).
"""

from __future__ import annotations

import re

import ahocorasick

from onto3gpp.ontology.schema import Concept, Ontology, Relation
from onto3gpp.ontology.tbox import TBox
from onto3gpp.parser import Section

# verb → relation type (lowercased verb stems)
_VERB_REL = {
    "selects": "selects",
    "select": "selects",
    "establishes": "establishes",
    "establish": "establishes",
    "forwards": "forwards",
    "forward": "forwards",
    "handles": "handles",
    "handle": "handles",
    "uses": "uses",
    "use": "uses",
    "connects": "connects",
    "connect": "connects",
    "carries": "carries",
    "carry": "carries",
    "maps": "maps",
    "map": "maps",
    "applies": "applies",
    "apply": "applies",
    "initiates": "initiates",
    "initiate": "initiates",
    "moves": "moves",
    "move": "moves",
    "updates": "updates",
    "update": "updates",
    "is": "is_a",
    "are": "is_a",
}

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def _concept_by_canonical(onto: Ontology) -> dict[str, Concept]:
    """Map lowercase canonical → Concept."""
    return {c.canonical.lower(): c for c in onto.concepts}


def _build_automaton(by_canonical: dict[str, Concept]) -> ahocorasick.Automaton:
    """Build a case-insensitive Aho-Corasick automaton over concept canonicals.

    Each key is the lowercase canonical; the value is the lowercase canonical
    itself (used to look up the concept). This gives O(text) matching instead
    of O(concepts) regex scans per sentence.
    """
    automaton = ahocorasick.Automaton()
    for canonical in by_canonical:
        automaton.add_word(canonical, canonical)
    if by_canonical:
        automaton.make_automaton()
    return automaton


def _find_concepts_in_sentence(
    sentence: str, by_canonical: dict[str, Concept], automaton: ahocorasick.Automaton
) -> list[tuple[Concept, int]]:
    """Return (concept, position) for concepts whose canonical appears in the
    sentence as a whole word (word-boundary match, case-insensitive).

    Uses an Aho-Corasick automaton for a single pass over the sentence. Only
    the first occurrence of each concept is kept (matching the previous
    regex-based behaviour).
    """
    found: list[tuple[Concept, int]] = []
    seen: set[str] = set()
    lower = sentence.lower()
    for end_index, canonical in automaton.iter(lower):
        start_index = end_index - len(canonical) + 1
        # word-boundary check: char before and after must not be alnum
        before = lower[start_index - 1] if start_index > 0 else " "
        after = lower[end_index + 1] if end_index + 1 < len(lower) else " "
        if before.isalnum() or after.isalnum():
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        found.append((by_canonical[canonical], start_index))
    return found


def extract_relations(
    sections: list[Section],
    onto: Ontology,
    tbox: TBox | None = None,
) -> list[Relation]:
    """Extract typed relations between known concepts from sections.

    If ``tbox`` is provided, each candidate relation is checked against the
    TBox before being emitted. A relation is dropped only when it can be
    *confidently* verified as invalid:

    - the relation type is not a known TBox relation type, or
    - both endpoint concept types are known TBox concept types and the
      ``(source.type, rel, target.type)`` edge is not allowed.

    If either endpoint's type is unknown to the TBox (e.g. the generic
    ``abbreviation``/``phrase`` types from the deterministic extractor), the
    relation is kept — we cannot verify it, so we stay permissive rather than
    silently dropping coverage. This keeps the deterministic-first path intact
    while letting AI-typed concepts (which carry TBox types) be schema-checked
    at extraction time.
    """
    by_canonical = _concept_by_canonical(onto)
    if not by_canonical:
        # no known concepts yet — nothing to relate
        return []
    automaton = _build_automaton(by_canonical)
    relations: list[Relation] = []

    for s in sections:
        for sentence in _SENTENCE_RE.findall(s.text):
            found = _find_concepts_in_sentence(sentence, by_canonical, automaton)
            if len(found) < 2:
                continue
            # find a verb between the first and last concept
            lower = sentence.lower()
            for verb, rel in _VERB_REL.items():
                vpos = lower.find(verb)
                if vpos == -1:
                    continue
                # source = concept before verb, target = concept after verb
                before = [c for c, p in found if p < vpos]
                after = [c for c, p in found if p > vpos]
                if before and after:
                    source, target = before[-1], after[0]
                    if tbox is not None and _violates_tbox(tbox, source, target, rel):
                        break  # one relation per sentence
                    relations.append(
                        Relation(
                            source=source.id,
                            rel=rel,
                            target=target.id,
                            weight=0.7,
                            confidence=0.8,
                            provenance={
                                "spec": s.spec,
                                "clause": s.clause,
                                "text_snippet": sentence.strip(),
                            },
                        )
                    )
                    break  # one relation per sentence

    return relations


def _violates_tbox(tbox: TBox, source: Concept, target: Concept, rel: str) -> bool:
    """Return True if the relation is *confidently* invalid per the TBox.

    A relation is dropped only when we can verify it violates the schema:
    the relation type is unknown, or both endpoint types are known TBox
    concept types and the edge is disallowed. If either endpoint type is not
    a known TBox concept type, we cannot verify the edge and keep it.
    """
    if not tbox.is_known_relation_type(rel):
        return True
    if not tbox.is_known_concept_type(source.type) or not tbox.is_known_concept_type(
        target.type
    ):
        return False
    return not tbox.allows(source.type, rel, target.type)
