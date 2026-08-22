"""Canvas via the per-user calendar feed (iCal) — the no-token route.

When an institution disables personal access tokens (e.g. UCF), the Canvas
Calendar still exposes a secret ICS URL ("Calendar Feed") that needs no token.
It carries assignment due dates and calendar events across all courses — enough
for deadline tracking, though not announcements or grades.

Parsed with the standard library only (no icalendar dependency).
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests


def _unfold(text: str) -> list[str]:
    """Join RFC 5545 folded lines (continuations begin with space/tab)."""
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    return (
        value.replace("\\n", " ").replace("\\N", " ")
        .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()
    )


def _parse_dt(value: str) -> str:
    """Normalize an ICS DTSTART value to an ISO-8601 string (best effort)."""
    v = value.strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            dt = datetime.strptime(v, fmt)
            if fmt.endswith("Z"):
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return v  # leave unrecognized formats untouched


def _course_from_summary(summary: str) -> str:
    """Canvas summaries often end with the course in brackets: 'Essay [ENG 101]'."""
    if summary.endswith("]") and "[" in summary:
        return summary[summary.rfind("[") + 1 : -1].strip()
    return ""


def parse_ics(text: str) -> list[dict]:
    events: list[dict] = []
    cur: dict | None = None
    for line in _unfold(text):
        if line.strip() == "BEGIN:VEVENT":
            cur = {}
        elif line.strip() == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, val = line.split(":", 1)
            name = key.split(";", 1)[0].upper()
            cur[name] = val
    out: list[dict] = []
    for e in events:
        summary = _unescape(e.get("SUMMARY", ""))
        due = e.get("DTSTART") or e.get("DTEND") or ""
        out.append(
            {
                "uid": e.get("UID", summary),
                "title": summary,
                "course": _course_from_summary(summary),
                "due_at": _parse_dt(due) if due else "",
            }
        )
    return out


def fetch(url: str) -> list[dict]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    return parse_ics(resp.text)
