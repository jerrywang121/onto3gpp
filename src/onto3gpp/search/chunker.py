"""Chunking: split sections into searchable chunks with metadata.

Each section becomes one or more chunks. Long sections are split into
character-bounded chunks that all carry the section's metadata. Splits prefer
sentence boundaries near the maximum chunk size, and consecutive chunks
overlap by a configurable number of characters so that a term straddling a
split boundary is not lost.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from onto3gpp.parser import Section

# A sentence boundary: a terminal punctuation mark (or newline) followed by
# whitespace. Used to split chunks on sentence boundaries.
_SENTENCE_END = re.compile(r"[.!?](?=\s)|(?<=\S)\n")


@dataclass
class Chunk:
    """A searchable chunk carrying its source section's metadata."""

    spec: str
    release: str
    clause: str
    title: str
    text: str


def _split_text(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split ``text`` into chunks of at most ``max_chars`` characters.

    Each split prefers the last sentence boundary within the window (so a
    chunk ends on a sentence close to ``max_chars``), falling back to a hard
    cut at ``max_chars`` when no boundary exists. Consecutive chunks overlap
    by ``overlap`` characters.
    """
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # Prefer the last sentence boundary inside the window so the chunk
            # ends near max_chars on a sentence boundary.
            window = text[start:end]
            matches = list(_SENTENCE_END.finditer(window))
            if matches:
                cut = matches[-1].end()
                if cut > 0:
                    end = start + cut
        chunks.append(text[start:end])
        if end >= n:
            break
        # Next chunk starts `overlap` chars before the previous cut, but must
        # always make forward progress.
        next_start = end - overlap
        start = next_start if next_start > start else start + 1
    return chunks


def chunk_sections(
    sections: list[Section],
    max_chars: int = 500,
    overlap: int = 80,
) -> list[Chunk]:
    """Convert sections into chunks, splitting long sections by character count.

    Each chunk carries its source section's metadata. ``max_chars`` is the
    target maximum chunk length in characters; ``overlap`` is the number of
    characters shared between consecutive chunks of the same section.
    """
    chunks: list[Chunk] = []
    for s in sections:
        if not s.text:
            continue
        for part in _split_text(s.text, max_chars, overlap):
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


def load_chunks(
    parsed_dir: Path,
    max_chars: int = 500,
    overlap: int = 80,
) -> list[Chunk]:
    """Load parsed JSONL sections from a directory and chunk them.

    Reads every ``*.jsonl`` file in ``parsed_dir`` (each line is a serialized
    :class:`Section`), reconstructs the sections, and chunks them with
    :func:`chunk_sections`.
    """
    sections: list[Section] = []
    for path in sorted(parsed_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            sections.append(
                Section(
                    spec=data["spec"],
                    release=data["release"],
                    clause=data["clause"],
                    title=data["title"],
                    text=data["text"],
                    parent_clause=data.get("parent_clause", ""),
                    metadata=data.get("metadata", {}),
                )
            )
    return chunk_sections(sections, max_chars=max_chars, overlap=overlap)
