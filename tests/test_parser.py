"""Tests for the document parser."""

from pathlib import Path

from onto3gpp.parser import Section, parse_docx, parse_pdf, parse_text


def test_parse_text_basic() -> None:
    text = """\
TS 23.501
5.6 PDU Session
5.6.1 General
The PDU session is established.
5.6.2 Procedures
The SMF selects a UPF.
"""
    sections = parse_text(text, spec="23.501", release="Rel-18")
    # Preamble section + one section per clause heading: 5.6, 5.6.1, 5.6.2
    assert len(sections) == 4
    assert sections[1].clause == "5.6"
    assert sections[2].clause == "5.6.1"
    assert sections[2].title == "General"
    assert "PDU session is established" in sections[2].text
    assert sections[2].spec == "23.501"
    assert sections[2].release == "Rel-18"


def test_parse_text_clause_hierarchy() -> None:
    text = """\
5.6 PDU Session
5.6.1 General
5.6.1.1 Sub
content here
"""
    sections = parse_text(text, spec="23.501", release="Rel-18")
    assert len(sections) == 3
    assert sections[2].clause == "5.6.1.1"
    assert sections[2].parent_clause == "5.6.1"


def test_parse_text_no_clauses() -> None:
    text = "Just a paragraph with no clause numbers."
    sections = parse_text(text, spec="23.501", release="Rel-18")
    assert len(sections) == 1
    assert sections[0].clause == ""
    assert sections[0].text == "Just a paragraph with no clause numbers."


def test_parse_docx(tmp_path: Path) -> None:
    from docx import Document

    doc = Document()
    doc.add_paragraph("5.6 PDU Session")
    doc.add_paragraph("5.6.1 General")
    doc.add_paragraph("The PDU session is established.")
    doc.add_paragraph("5.6.1.1\tSub\t114")  # TOC entry → dropped
    doc.add_paragraph("5.6.2 Procedures")
    doc.add_paragraph("The SMF selects a UPF.")
    path = tmp_path / "spec.docx"
    doc.save(str(path))

    sections = parse_docx(path, spec="38.300", release="Rel-18")
    # 5.6 + 5.6.1 + 5.6.2 (TOC entry dropped, no preamble)
    assert len(sections) == 3
    assert sections[0].clause == "5.6"
    assert sections[1].clause == "5.6.1"
    assert "PDU session is established" in sections[1].text
    assert sections[2].clause == "5.6.2"


def test_parse_text_drops_toc_entries_with_dotted_leaders() -> None:
    """TOC entries (clause heading + dotted leader + page number) are dropped."""
    text = """\
5.6 PDU Session
5.6.1 General
The PDU session is established.
5.6.2 Procedures
The SMF selects a UPF.
5.6.1 General....................................................114
5.6.2 Procedures.................................................115
"""
    sections = parse_text(text, spec="38.300", release="Rel-18")
    # 5.6 + 5.6.1 + 5.6.2 (the two dotted-leader TOC lines are dropped)
    assert len(sections) == 3
    assert sections[0].clause == "5.6"
    assert sections[1].clause == "5.6.1"
    assert sections[2].clause == "5.6.2"


def test_parse_pdf(tmp_path: Path) -> None:
    """parse_pdf reads a pre-extracted .txt and parses it like parse_file."""
    txt = tmp_path / "spec.txt"
    txt.write_text(
        "5.6 PDU Session\n5.6.1 General\nThe PDU session is established.\n",
        encoding="utf-8",
    )
    sections = parse_pdf(txt, spec="38.331", release="Rel-19")
    assert len(sections) == 2
    assert sections[0].clause == "5.6"
    assert sections[1].clause == "5.6.1"
    assert sections[1].spec == "38.331"
    assert sections[1].release == "Rel-19"


def test_parse_text_skips_spurious_clauses_from_noisy_pdf() -> None:
    """Body lines that start with numbers are not treated as clause headings."""
    text = """\
5.6 PDU Session
5.6.1 General
The PDU session is established.
172800 means 172800s or longer.
3 hours. The UE shall discard any stored segments.
650 Route des Lucioles
5.6.2 Procedures
The SMF selects a UPF.
"""
    sections = parse_text(text, spec="38.300", release="Rel-18")
    clauses = [s.clause for s in sections]
    assert clauses == ["5.6", "5.6.1", "5.6.2"]
    # the spurious lines accumulate into the 5.6.1 section text
    assert "172800" in sections[1].text
    assert "650 Route" in sections[1].text


def test_parse_text_skips_wrapped_toc_block() -> None:
    """A TOC block whose entries wrap across lines is skipped entirely."""
    text = """\
Contents
1 Scope ......................................................30
2 References .................................................33
5.3.3.6 Cell re-selection or cell selection or relay (re)selection while T390, T
300 or T302 is running (UE
        in RRC_IDLE) .........................................95
1     Scope
The present document specifies the RRC protocol.
2     References
The following documents contain provisions.
"""
    sections = parse_text(text, spec="38.331", release="Rel-19")
    clauses = [s.clause for s in sections]
    # only the real body headings survive; the wrapped TOC entry is dropped
    assert clauses == ["1", "2"]
    assert "Cell re-selection" not in " ".join(s.text for s in sections)


def test_parse_text_skips_nas_table_rows() -> None:
    """NAS specs (e.g. TS 24.501) have table rows that start with a number and
    an uppercase title but are not real top-level headings. Only headings whose
    title appears in the TOC are kept."""
    text = """\
Contents
1 Scope ......................................................28
2 References .................................................28
3 Definitions and abbreviations ...............................33
4 General ....................................................50
5 Elementary procedures for 5GS mobility management ...........165
6 Elementary procedures for 5GS session management ............578
7 Handling of unknown, unforeseen, and erroneous protocol data ...777
8 Message functional definitions and contents .................783
9 General message format and information elements coding ......866
10 List of system parameters ..................................1128
1     Scope
The present document specifies the 5GS NAS protocol.
2     References
The following documents contain provisions.
3     Definitions and abbreviations
4     General
5     Elementary procedures for 5GS mobility
6     Elementary procedures for 5GS session
7     Handling of unknown, unforeseen, and erroneous
8     Message functional definitions and contents
9     General message format and information elements
10    List of system parameters
0     UE is not configured with any parameters from this table
1     UAS services enabled
21    Authentication parameter RAND
5     MO MMTel voice call; or
"""
    sections = parse_text(text, spec="24.501", release="Rel-19")
    clauses = [s.clause for s in sections]
    # only the 10 real top-level headings survive; table rows are dropped
    assert clauses == ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]
    # the spurious table rows accumulate into the last section's text
    assert "UAS services enabled" in sections[-1].text
    assert "Authentication parameter RAND" in sections[-1].text
