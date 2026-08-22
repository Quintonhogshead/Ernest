"""The approval queue for calendar writes Ernest doesn't own outright.

Mirroring existing events (jobs/gcal_sync.py) writes directly — it's a copy of
a commitment that already exists elsewhere. Anything that represents a NEW
commitment (Quinton asking Ernest to add/move/cancel something via chat) goes
through propose() → a Discord message → approve()/deny() before gcal.py is
ever called. This is Ernest's first write capability, so nothing here executes
without an explicit human decision.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from . import gcal
from .audit import log_event
from .config import Config


def propose(conn: sqlite3.Connection, kind: str, payload: dict, description: str) -> int:
    cur = conn.execute(
        "INSERT INTO pending_actions (kind, payload, description, status, created_at) "
        "VALUES (?, ?, ?, 'pending', ?)",
        (kind, json.dumps(payload), description, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    log_event("gcal_actions", "proposed", {"id": cur.lastrowid, "kind": kind})
    return cur.lastrowid


def _load_pending(conn: sqlite3.Connection, action_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM pending_actions WHERE id = ? AND status = 'pending'", (action_id,)
    ).fetchone()


def _decide(conn: sqlite3.Connection, action_id: int, status: str) -> None:
    conn.execute(
        "UPDATE pending_actions SET status = ?, decided_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), action_id),
    )
    conn.commit()


def deny(conn: sqlite3.Connection, action_id: int) -> str:
    row = _load_pending(conn, action_id)
    if not row:
        return f"No pending action #{action_id} to deny."
    _decide(conn, action_id, "denied")
    log_event("gcal_actions", "denied", {"id": action_id})
    return f"Denied — I won't do: {row['description']}"


def execute(cfg: Config, conn: sqlite3.Connection, action_id: int) -> str:
    row = _load_pending(conn, action_id)
    if not row:
        return f"No pending action #{action_id} to approve."
    payload = json.loads(row["payload"])
    try:
        if row["kind"] == "gcal_create":
            gcal.create_event(cfg, payload["account"], payload["calendar_id"], payload["event"])
        elif row["kind"] == "gcal_update":
            gcal.update_event(cfg, payload["account"], payload["calendar_id"],
                              payload["event_id"], payload["event"])
        elif row["kind"] == "gcal_delete":
            gcal.delete_event(cfg, payload["account"], payload["calendar_id"],
                              payload["event_id"])
        else:
            raise ValueError(f"unknown action kind: {row['kind']}")
    except Exception as exc:
        _decide(conn, action_id, "failed")
        log_event("gcal_actions", "failed", {"id": action_id, "error": str(exc)})
        return f"Couldn't do it — {exc}"
    _decide(conn, action_id, "executed")
    log_event("gcal_actions", "executed", {"id": action_id, "kind": row["kind"]})
    return f"Done — {row['description']}"
