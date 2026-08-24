"""Document parsing (text/docx/pdf) → structured sections.

Stage 0 baseline: parse plain text into clause-structured sections. The
parser is domain-agnostic — it reads document metadata (spec, release) and
splits text on clause-number headings.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Matches a clause heading like "5.6.1 General" or "5.6 PDU Session"
_CLAUSE_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")


@dataclass
class Section:
    """A structured section of a document."""

    spec: str
    release: str
    clause: str
    title: str
    text: str
    parent_clause: str = ""
    metadata: dict = field(default_factory=dict)


def _parent_of(clause: str) -> str:
    """Return the parent clause of a dotted clause number, or '' if none."""
    parts = clause.split(".")
    if len(parts) <= 1:
        return ""
    return ".".join(parts[:-1])


def parse_text(text: str, spec: str, release: str) -> list[Section]:
    """Parse plain text into clause-structured sections.

    Lines that look like clause headings ("5.6.1 Title") start a new section.
    All other lines accumulate into the current section's text.
    """
    sections: list[Section] = []
    current: Section | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _CLAUSE_RE.match(line)
        if m:
            clause, title = m.group(1), m.group(2)
            current = Section(
                spec=spec,
                release=release,
                clause=clause,
                title=title,
                text="",
                parent_clause=_parent_of(clause),
            )
            sections.append(current)
        else:
            if current is None:
                # Text before any clause heading → a single unnamed section
                current = Section(
                    spec=spec,
                    release=release,
                    clause="",
                    title="",
                    text="",
                )
                sections.append(current)
            current.text = (current.text + " " + line).strip()

    return sections


def parse_file(path: Path, spec: str, release: str) -> list[Section]:
    """Parse a text file into sections."""
    return parse_text(path.read_text(encoding="utf-8"), spec=spec, release=release)
