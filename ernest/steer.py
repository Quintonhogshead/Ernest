"""User-steerable rules, set from Discord and persisted in the settings store.

Today this is priority overrides: senders and keywords Quinton tells Ernest to
always flag, layered ON TOP of the ones in .env (ERNEST_PRIORITY_*). Storing
them in the DB rather than .env means the running bot can change them live —
no redeploy — and triage merges both sources at classify time.
"""

from __future__ import annotations

import json
import sqlite3

from .store import get_setting, set_setting

_SENDERS_KEY = "steer.priority_senders"
_KEYWORDS_KEY = "steer.priority_keywords"


def _key(kind: str) -> str:
    return _SENDERS_KEY if kind == "sender" else _KEYWORDS_KEY


def _load(conn: sqlite3.Connection, key: str) -> list[str]:
    raw = get_setting(conn, key)
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except Exception:
        return []
    return [str(x) for x in val] if isinstance(val, list) else []


def priority_rules(conn: sqlite3.Connection) -> tuple[list[str], list[str]]:
    """(senders, keywords) the user has added from Discord."""
    return _load(conn, _SENDERS_KEY), _load(conn, _KEYWORDS_KEY)


def add(conn: sqlite3.Connection, kind: str, value: str) -> bool:
    """Add a sender/keyword priority rule. False if empty or already present."""
    value = (value or "").strip()
    if not value:
        return False
    key = _key(kind)
    vals = _load(conn, key)
    if any(v.lower() == value.lower() for v in vals):
        return False
    vals.append(value)
    set_setting(conn, key, json.dumps(vals))
    return True


def remove(conn: sqlite3.Connection, kind: str, value: str) -> bool:
    """Remove a sender/keyword priority rule. False if it wasn't there."""
    value = (value or "").strip()
    key = _key(kind)
    vals = _load(conn, key)
    keep = [v for v in vals if v.lower() != value.lower()]
    if len(keep) == len(vals):
        return False
    set_setting(conn, key, json.dumps(keep))
    return True
