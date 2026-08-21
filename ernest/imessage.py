"""iMessage/SMS reader — read-only, macOS only.

Reads a *copy* of the local Messages database. Requires Full Disk Access for the
Python that runs the job. There is no reply path anywhere in this codebase.
Newer macOS stores some message text in a binary ``attributedBody`` blob rather
than the ``text`` column; ``decode()`` handles the common NSString layout.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

from . import ErnestError

# Apple epoch: 2001-01-01 UTC, stored in nanoseconds.
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
_DB = os.path.expanduser("~/Library/Messages/chat.db")
_COPY_DIR = os.path.join("state", "tmp")


class IMessageError(ErnestError):
    """chat.db could not be read (usually missing Full Disk Access)."""


def _apple_ns_to_dt(value: int) -> datetime:
    return _APPLE_EPOCH + timedelta(seconds=value / 1_000_000_000)


def decode(text: str | None, attributed_body: bytes | None) -> str | None:
    """Prefer the plain text column; else decode the NSString in the blob."""
    if text:
        return text
    if not attributed_body:
        return None
    try:
        blob = attributed_body
        marker = blob.find(b"NSString")
        if marker == -1:
            return None
        i = marker + len(b"NSString") + 6
        if i >= len(blob):
            return None
        if blob[i] == 0x81:  # 2-byte little-endian length prefix
            length = int.from_bytes(blob[i + 1 : i + 3], "little")
            start = i + 3
        else:
            length = blob[i]
            start = i + 1
        return blob[start : start + length].decode("utf-8", errors="replace") or None
    except Exception:
        return None


def _open_copy() -> sqlite3.Connection:
    if not os.path.exists(_DB):
        raise IMessageError("~/Library/Messages/chat.db not found (macOS only)")
    os.makedirs(_COPY_DIR, exist_ok=True)
    dest = os.path.join(_COPY_DIR, "chat_copy.db")
    try:
        shutil.copy2(_DB, dest)
        for ext in ("-wal", "-shm"):
            if os.path.exists(_DB + ext):
                shutil.copy2(_DB + ext, dest + ext)
    except PermissionError as exc:
        raise IMessageError(
            "cannot read chat.db — grant Full Disk Access to this terminal/python"
        ) from exc
    return sqlite3.connect(f"file:{dest}?mode=ro", uri=True)


def recent(hours: int = 24) -> list[dict]:
    conn = _open_copy()
    conn.row_factory = sqlite3.Row
    cutoff_ns = int(
        (datetime.now(timezone.utc) - timedelta(hours=hours) - _APPLE_EPOCH).total_seconds()
        * 1_000_000_000
    )
    rows = conn.execute(
        """
        SELECT m.ROWID AS rowid, m.date AS date, m.text AS text,
               m.attributedBody AS body, m.is_from_me AS is_from_me,
               h.id AS sender
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        WHERE m.date > ?
        ORDER BY m.date DESC
        """,
        (cutoff_ns,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        body = decode(r["text"], r["body"])
        if not body:
            continue
        out.append(
            {
                "rowid": r["rowid"],
                "sender": r["sender"] or "(unknown)",
                "text": body,
                "is_from_me": bool(r["is_from_me"]),
                "date": _apple_ns_to_dt(r["date"]).isoformat(),
            }
        )
    conn.close()
    return out
