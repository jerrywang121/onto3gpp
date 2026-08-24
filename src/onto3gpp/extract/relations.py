"""Relation extraction (Stage 2).

Rules-based extraction of typed relations between known ontology concepts.
For each sentence, find known concepts (via the compiled dictionary) and
detect verbs that map to relation types. This is the deterministic, AI-free
path; an LLM path can be added later (see extract_relations.txt).

Verb → relation-type mapping is domain-agnostic (common English verbs).
"""

from __future__ import annotations

import re

from onto3gpp.ontology.schema import Concept, Ontology, Relation
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


def _find_concepts_in_sentence(
    sentence: str, by_canonical: dict[str, Concept]
) -> list[tuple[Concept, int]]:
    """Return (concept, position) for concepts whose canonical appears in the
    sentence as a whole word (word-boundary match, case-insensitive)."""
    found: list[tuple[Concept, int]] = []
    lower = sentence.lower()
    for canonical, concept in by_canonical.items():
        # word-boundary match so short abbreviations ("re", "up") don't match
        # inside longer words ("procedure", "support")
        pattern = r"(?<![a-z0-9])" + re.escape(canonical.lower()) + r"(?![a-z0-9])"
        m = re.search(pattern, lower)
        if m:
            found.append((concept, m.start()))
    return found


def extract_relations(sections: list[Section], onto: Ontology) -> list[Relation]:
    """Extract typed relations between known concepts from sections."""
    by_canonical = _concept_by_canonical(onto)
    relations: list[Relation] = []

    for s in sections:
        for sentence in _SENTENCE_RE.findall(s.text):
            found = _find_concepts_in_sentence(sentence, by_canonical)
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
