"""Ontology compiler → compiled dictionary (Stage 1).

Compiles gated candidate terms into a searchable dictionary backed by an
Aho-Corasick automaton (via `pyahocorasick`). The dictionary maps every
surface form (canonical + aliases + abbreviations) to a canonical term, so
runtime NER can resolve any surface form to its canonical concept.

The compiled dictionary is serializable (JSON) so it can be shipped to the
deterministic runtime without any AI dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import ahocorasick

from onto3gpp.extract.terms import CandidateTerm


@dataclass
class DictionaryEntry:
    """A compiled dictionary entry: a surface form → canonical term."""

    surface: str
    canonical: str
    type: str  # "abbreviation" | "phrase"
    aliases: list[str] = field(default_factory=list)


@dataclass
class Dictionary:
    """A compiled terminology dictionary with an Aho-Corasick automaton."""

    entries: dict[str, DictionaryEntry]
    automaton: ahocorasick.Automaton | None = None
    # maps lowercase surface form → original surface form (for case-insensitive match)
    _lower_to_surface: dict[str, str] = field(default_factory=dict)

    def find(self, text: str) -> list[str]:
        """Return the canonical terms found in text (longest-match aware).

        Uses the Aho-Corasick automaton (case-insensitive) to find all surface
        forms, then resolves each to its canonical term. Returns canonical
        terms in order of first occurrence.

        Matches are required to sit on word boundaries: a surface form only
        counts if the characters immediately before and after it are not
        alphanumeric. This prevents short abbreviations (e.g. "RA", "AR")
        from matching inside longer words (e.g. "RAN", "area").
        """
        if self.automaton is None:
            return []
        found: list[str] = []
        seen: set[str] = set()
        lower = text.lower()
        for end_index, lower_surface in self.automaton.iter(lower):
            start_index = end_index - len(lower_surface) + 1
            # word-boundary check: char before and after must not be alnum
            before = lower[start_index - 1] if start_index > 0 else " "
            after = lower[end_index + 1] if end_index + 1 < len(lower) else " "
            if before.isalnum() or after.isalnum():
                continue
            surface = self._lower_to_surface.get(lower_surface, lower_surface)
            entry = self.entries[surface]
            if entry.canonical not in seen:
                seen.add(entry.canonical)
                found.append(entry.canonical)
        return found

    def to_dict(self) -> dict:
        """Serialize the dictionary (entries only; automaton is rebuilt)."""
        return {
            "entries": [
                {
                    "surface": e.surface,
                    "canonical": e.canonical,
                    "type": e.type,
                    "aliases": e.aliases,
                }
                for e in self.entries.values()
            ]
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Dictionary":
        """Deserialize a dictionary and rebuild the automaton."""
        entries = {
            e["surface"]: DictionaryEntry(
                surface=e["surface"],
                canonical=e["canonical"],
                type=e["type"],
                aliases=e["aliases"],
            )
            for e in data["entries"]
        }
        return build_automaton(entries)


def build_automaton(entries: dict[str, DictionaryEntry]) -> Dictionary:
    """Build an Aho-Corasick automaton over the entry surface forms.

    The automaton is case-insensitive: keys are lowercased, and a map from
    lowercase → original surface is kept for resolution.
    """
    if not entries:
        # pyahocorasick cannot make_automaton() on an empty trie; leave the
        # automaton as None so Dictionary.find() returns [] (it already guards
        # on `self.automaton is None`).
        return Dictionary(entries=entries, automaton=None, _lower_to_surface={})
    automaton = ahocorasick.Automaton()
    lower_to_surface: dict[str, str] = {}
    for surface in entries:
        lower = surface.lower()
        automaton.add_word(lower, lower)
        lower_to_surface[lower] = surface
    automaton.make_automaton()
    return Dictionary(
        entries=entries,
        automaton=automaton,
        _lower_to_surface=lower_to_surface,
    )


def build_dictionary(terms: list[CandidateTerm]) -> Dictionary:
    """Compile gated candidate terms into a Dictionary.

    Each term contributes its canonical form plus its aliases/abbreviations
    as surface forms, all resolving to the canonical term.
    """
    entries: dict[str, DictionaryEntry] = {}
    for term in terms:
        canonical = term.canonical
        # canonical surface form
        entries[canonical] = DictionaryEntry(
            surface=canonical,
            canonical=canonical,
            type=term.type,
            aliases=list(term.aliases),
        )
        # aliases and abbreviations resolve to canonical
        for alias in list(term.aliases) + list(term.abbreviations):
            if alias and alias != canonical:
                entries[alias] = DictionaryEntry(
                    surface=alias,
                    canonical=canonical,
                    type=term.type,
                    aliases=list(term.aliases),
                )
    return build_automaton(entries)
