"""Library tests: chunking + ingest + hybrid search, using FTS only (no keys)."""

import os

import pytest

from ernest.config import Config
from ernest.library import add_document, chunk_text, search
from ernest.store import connect, has_fts


@pytest.fixture()
def conn(tmp_path):
    db = os.path.join(tmp_path, "t.db")
    return connect(db)


@pytest.fixture()
def cfg():
    # No OpenAI key → embeddings skipped, ingestion + FTS still work.
    return Config()


def test_chunk_text_paragraphs():
    text = "\n\n".join([f"Paragraph {i} " + "x" * 100 for i in range(20)])
    chunks = chunk_text(text, size=400)
    assert len(chunks) > 1
    assert all(len(c) <= 800 for c in chunks)  # generous bound incl. joins


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_ingest_and_dedup(conn, cfg):
    n1 = add_document(conn, cfg, "file:a", "A", "The cover design uses a serif font.")
    assert n1 >= 1
    n2 = add_document(conn, cfg, "file:a", "A", "The cover design uses a serif font.")
    assert n2 == 0  # same text fingerprint → not re-ingested
    assert add_document(conn, cfg, "file:b", "B", "") == 0


def test_search_finds_keyword(conn, cfg):
    if not has_fts(conn):
        pytest.skip("FTS5 not available in this SQLite build")
    add_document(conn, cfg, "gmail:work", "Karli sync",
                 "We discussed Social Media Pro pricing and the launch timeline.")
    add_document(conn, cfg, "gmail:work", "Unrelated",
                 "Reminder about the office parking policy.")
    hits = search(conn, cfg, "Social Media Pro", k=5)
    assert hits
    assert "Social Media Pro" in hits[0]["chunk"]


def test_search_multiword_query_not_strict_phrase(conn, cfg):
    # A multi-word query must not require the exact phrase to appear verbatim.
    if not has_fts(conn):
        pytest.skip("FTS5 not available in this SQLite build")
    add_document(conn, cfg, "gmail:work", "Karli sync",
                 "We agreed Social Media Pro will launch in Q3 at $49/mo.")
    hits = search(conn, cfg, "Social Media Pro launch price", k=3)
    assert hits, "multi-word query should still retrieve the relevant chunk"
    assert "Social Media Pro" in hits[0]["chunk"]


def test_search_empty_library(conn, cfg):
    assert search(conn, cfg, "anything", k=5) == []
