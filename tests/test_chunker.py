"""Tests for the chunker."""

from onto3gpp.parser import Section
from onto3gpp.search.chunker import chunk_sections


def _section(clause: str, title: str, text: str) -> Section:
    return Section(
        spec="23.501",
        release="Rel-18",
        clause=clause,
        title=title,
        text=text,
        parent_clause="5.6" if clause.count(".") >= 2 else "",
    )


def test_chunk_sections_metadata() -> None:
    sections = [_section("5.6.1", "General", "The PDU session is established.")]
    chunks = chunk_sections(sections)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.spec == "23.501"
    assert c.release == "Rel-18"
    assert c.clause == "5.6.1"
    assert c.title == "General"
    assert c.text == "The PDU session is established."


def test_chunk_sections_splits_long_text() -> None:
    long_text = "word " * 500  # 500 words
    sections = [_section("5.6.1", "General", long_text)]
    chunks = chunk_sections(sections, max_words=100)
    assert len(chunks) > 1
    # Each chunk (except possibly the last) has <= max_words
    for c in chunks[:-1]:
        assert len(c.text.split()) <= 100
