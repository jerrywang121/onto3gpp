"""Tests for the chunker."""

from itertools import pairwise

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
    long_text = "word " * 500  # 500 words, no sentence boundaries
    sections = [_section("5.6.1", "General", long_text)]
    chunks = chunk_sections(sections, max_chars=100, overlap=0)
    assert len(chunks) > 1
    # Each chunk (except possibly the last) has <= max_chars characters.
    for c in chunks[:-1]:
        assert len(c.text) <= 100


def test_chunk_sections_splits_on_sentence_boundary() -> None:
    # A long text made of short sentences. Chunks should end on a sentence
    # boundary close to max_chars, never mid-sentence.
    sentence = "The PDU session is established by the SMF. "
    text = sentence * 20
    sections = [_section("5.6.1", "General", text)]
    chunks = chunk_sections(sections, max_chars=100, overlap=0)
    assert len(chunks) > 1
    for c in chunks:
        # Each chunk ends with a sentence terminator (or is the whole text).
        assert c.text.rstrip().endswith(".")


def test_chunk_sections_overlap() -> None:
    # With overlap, consecutive chunks share trailing/leading characters.
    text = "word " * 300  # no sentence boundaries -> hard cuts
    sections = [_section("5.6.1", "General", text)]
    chunks = chunk_sections(sections, max_chars=100, overlap=20)
    assert len(chunks) > 1
    for a, b in pairwise(chunks):
        # The next chunk starts `overlap` chars before the previous cut.
        assert a.text[-20:] == b.text[:20]