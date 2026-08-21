"""SQLite state: seen-IDs, triaged messages, Canvas items, and the library.

One file at ``state/ernest.db``. The library tables (FTS5 + an embeddings
column) power retrieval; see ernest/library.py. Schema is applied idempotently
on every connect, so upgrades are safe.
"""

from __future__ import annotations

import os
import sqlite3

# Honor ERNEST_DB_PATH so the app can point at a mounted volume (e.g. on Fly.io);
# defaults to a local file for laptop runs.
DB_PATH = os.environ.get("ERNEST_DB_PATH") or os.path.join("state", "ernest.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen (
  kind        TEXT NOT NULL,
  external_id TEXT NOT NULL,
  first_seen  TEXT NOT NULL,
  PRIMARY KEY (kind, external_id)
);

CREATE TABLE IF NOT EXISTS messages (
  gmail_id   TEXT PRIMARY KEY,
  account    TEXT NOT NULL,
  sender     TEXT,
  subject    TEXT,
  category   TEXT NOT NULL,
  summary    TEXT,
  urgent     INTEGER NOT NULL DEFAULT 0,
  triaged_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS canvas_items (
  item_id TEXT PRIMARY KEY,
  course  TEXT,
  title   TEXT,
  kind    TEXT,
  due_at  TEXT,
  seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS library (
  id        INTEGER PRIMARY KEY,
  source    TEXT NOT NULL,
  title     TEXT,
  chunk     TEXT NOT NULL,
  embedding BLOB,
  ts        TEXT NOT NULL
);
"""

_FTS = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS library_fts "
    "USING fts5(chunk, title, source, content='library', content_rowid='id')"
)


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    try:
        conn.execute(_FTS)
    except sqlite3.OperationalError:
        # FTS5 not compiled into this SQLite build — library falls back to
        # embedding-only search (see library.search()).
        pass
    conn.commit()
    return conn


def has_fts(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_fts'"
    ).fetchone()
    return row is not None


def mark_seen(conn: sqlite3.Connection, kind: str, external_id: str) -> bool:
    """Record (kind, external_id). Return True if newly seen, False if a repeat."""
    from datetime import datetime, timezone

    try:
        conn.execute(
            "INSERT INTO seen (kind, external_id, first_seen) VALUES (?, ?, ?)",
            (kind, str(external_id), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
