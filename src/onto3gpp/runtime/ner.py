"""Runtime NER (dictionary path, Stage 1).

Deterministic, CPU-only named-entity recognition using the compiled
dictionary's Aho-Corasick automaton. This is the runtime query path — no AI.

- `annotate(text)` → canonical terms found in the text.
- `expand_query(query)` → the query plus its canonical terms, for BM25
  expansion.
"""

from __future__ import annotations

from onto3gpp.compile.dictionary import Dictionary
from onto3gpp.search.bm25 import tokenize


def annotate(dictionary: Dictionary, text: str) -> list[str]:
    """Return the canonical terms found in text, in order of occurrence."""
    return dictionary.find(text)


def expand_query(dictionary: Dictionary, query: str) -> list[str]:
    """Expand a query with canonical terms and their surface forms.

    Returns the original query tokens plus the canonical terms and their
    aliases/abbreviations, so BM25 can match on both the surface form and the
    full concept name.
    """
    tokens = tokenize(query)
    canonicals = annotate(dictionary, query)
    for canonical in canonicals:
        # add the canonical term's tokens
        for tok in tokenize(canonical):
            if tok not in tokens:
                tokens.append(tok)
        # add all surface forms (aliases/abbreviations) of the canonical term
        for surface, entry in dictionary.entries.items():
            if entry.canonical == canonical:
                for tok in tokenize(surface):
                    if tok not in tokens:
                        tokens.append(tok)
    return tokens
