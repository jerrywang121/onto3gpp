"""Chunking: split sections into searchable chunks with metadata.

Stage 0 baseline: each section becomes one chunk, but long sections are split
into word-bounded chunks that all carry the section's metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

from onto3gpp.parser import Section


@dataclass
class Chunk:
    """A searchable chunk carrying its source section's metadata."""

    spec: str
    release: str
    clause: str
    title: str
    text: str


def chunk_sections(sections: list[Section], max_words: int = 200) -> list[Chunk]:
    """Convert sections into chunks, splitting long sections by word count."""
    chunks: list[Chunk] = []
    for s in sections:
        words = s.text.split()
        if not words:
            continue
        for i in range(0, len(words), max_words):
            part = " ".join(words[i : i + max_words])
            chunks.append(
                Chunk(
                    spec=s.spec,
                    release=s.release,
                    clause=s.clause,
                    title=s.title,
                    text=part,
                )
            )
    return chunks
