"""Append-only audit log.

Every read batch, classification, digest, and (future) action appends one JSON
line to ``logs/audit.jsonl``. The evening wrap is generated from this file, so
silent action is impossible by construction. Logging never raises.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

LOG_PATH = os.path.join("logs", "audit.jsonl")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(job: str, action: str, detail: dict | None = None) -> None:
    """Append one event. Best-effort: on failure, warn to stderr and continue."""
    record = {"ts": _now(), "job": job, "action": action, "detail": detail or {}}
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:  # never let logging break a job
        print(f"[audit] failed to write event: {exc}", file=sys.stderr)


def read_events(since_iso: str | None = None) -> list[dict]:
    """Return audit events, optionally only those at/after ``since_iso``."""
    if not os.path.exists(LOG_PATH):
        return []
    out: list[dict] = []
    with open(LOG_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if since_iso and rec.get("ts", "") < since_iso:
                continue
            out.append(rec)
    return out
