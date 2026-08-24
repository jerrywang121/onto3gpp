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

# A table-of-contents entry: a clause heading followed by a dotted leader and
# a page number, e.g. "5.6.1 General....................114". These appear in
# the front-matter TOC and must be dropped, not parsed as body sections.
_TOC_RE = re.compile(r"^(\d+(?:\.\d+)*)\s+.+\.{3,}\s*\d+\s*$")


def _is_spurious_clause(clause: str, title: str) -> bool:
    """True if a ``_CLAUSE_RE`` match is a false positive from noisy PDF text
    extraction, not a real clause heading.

    PDF text extraction (e.g. LiteParse) can split body lines so that a line
    starts with a number followed by text. Heuristics to reject those:

    * first segment has >2 digits (page/byte offsets, values like ``172800``);
    * title does not start with an uppercase letter (real headings are
      capitalized; body fragments like ``sk-Counter ...`` are rare);
    * title ends in sentence punctuation (``.`` ``!`` ``?`` ``:`` ``;``) —
      real headings don't end in punctuation.
    """
    if len(clause.split(".")[0]) > 2:
        return True
    if not re.match(r"^[A-Z]", title):
        return True
    if re.search(r"[.!?:;]\s*$", title):
        return True
    return False


def _norm_toc_title(title: str) -> str:
    """Normalize a TOC title: strip dotted leaders and page numbers, collapse
    whitespace. Handles TOC entries that wrap across lines (a continuation line
    has no dotted leader on the same line, so the captured title may contain
    embedded newlines and leader fragments)."""
    t = re.sub(r"\s*\.{3,}\s*\d*\s*", " ", title)
    return re.sub(r"\s+", " ", t).strip()


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

    The front-matter table of contents is skipped as a block: it is entered on
    the "Contents" heading or the first dotted-leader line, and exited on the
    first top-level (non-dotted) clause heading that is not itself a TOC entry.
    This handles TOC entries that wrap across lines (a continuation line like
    "5.3.3.6 Cell re-selection ..." has no dotted leader on the same line).

    While scanning the TOC, the normalized titles of single-number (top-level)
    entries are collected. Body lines whose clause is a single number are only
    accepted as headings if their title is a prefix of one of those TOC titles.
    This rejects table rows and bit-field enumerations (e.g. NAS specs like
    TS 24.501 have rows like "1 UAS services enabled" or "21 Authentication
    parameter RAND") that start with a number but are not real top-level
    headings. Real top-level headings (1-10) always appear in the TOC.
    """
    sections: list[Section] = []
    current: Section | None = None
    in_toc = False
    toc_top_level: set[str] = set()

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # enter the table of contents block
        if not in_toc and (line == "Contents" or _TOC_RE.match(line)):
            in_toc = True
            continue
        if in_toc:
            m = _CLAUSE_RE.match(line)
            if m and "." not in m.group(1) and not _TOC_RE.match(line) \
                    and not _is_spurious_clause(m.group(1), m.group(2)):
                in_toc = False
            else:
                # record single-number TOC entries (real top-level headings)
                if m and "." not in m.group(1) and _TOC_RE.match(line):
                    toc_top_level.add(_norm_toc_title(m.group(2)))
                continue
        m = _CLAUSE_RE.match(line)
        if m and not _is_spurious_clause(m.group(1), m.group(2)):
            clause, title = m.group(1), m.group(2)
            # a single-number heading is only real if its title is a prefix of
            # a TOC top-level title (rejects table rows / bit-field values)
            if "." not in clause and toc_top_level:
                nt = _norm_toc_title(title)
                if not any(t.startswith(nt) or nt.startswith(t)
                           for t in toc_top_level):
                    if current is None:
                        current = Section(
                            spec=spec,
                            release=release,
                            clause="",
                            title="",
                            text="",
                        )
                        sections.append(current)
                    current.text = (current.text + " " + line).strip()
                    continue
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


def parse_pdf(path: Path, spec: str, release: str) -> list[Section]:
    """Parse a PDF that has been pre-extracted to a .txt file.

    PDF text extraction is delegated to an external tool (e.g. LiteParse's
    ``lit parse --format text``). This function reads the extracted text and
    feeds it through :func:`parse_text`, so PDFs share the same clause
    structure as text/docx sources.
    """
    return parse_text(path.read_text(encoding="utf-8"), spec=spec, release=release)


def _is_toc_entry(line: str) -> bool:
    """True if a clause heading is a table-of-contents entry (ends in a page
    number), e.g. "5.6.1 General\t114"."""
    m = _CLAUSE_RE.match(line)
    if not m:
        return False
    parts = line.split()
    return bool(parts) and parts[-1].isdigit()


def parse_docx(path: Path, spec: str, release: str) -> list[Section]:
    """Parse a .docx file into sections.

    Extracts paragraph text, drops table-of-contents entries (clause headings
    that end in a page number), and feeds the rest to :func:`parse_text`.
    """
    from docx import Document

    doc = Document(str(path))
    lines = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    body = [ln for ln in lines if not _is_toc_entry(ln)]
    return parse_text("\n".join(body), spec=spec, release=release)
