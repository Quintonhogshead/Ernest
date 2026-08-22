"""Canvas poller → Discord digest. Read-only.

Two sources, auto-selected:
  * CANVAS_ICS_URL set  → the no-token calendar feed (due dates only). Use this
    when your school disables access tokens (e.g. UCF).
  * CANVAS_TOKEN set    → the REST API (due dates + announcements, ingested).

Populates the canvas_items table so the morning brief's "due within 72h" works.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ernest import canvas, canvas_ics, chan, library
from ernest.audit import log_event
from ernest.canvas import CanvasAuthError
from ernest.config import load
from ernest.guard import halt_if_paused
from ernest.store import connect, mark_seen


def _upsert_item(conn, item_id, course, title, kind, due_at):
    conn.execute(
        "INSERT OR REPLACE INTO canvas_items (item_id, course, title, kind, due_at, seen_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item_id, course, title, kind, due_at, datetime.now(timezone.utc).isoformat()),
    )


def _via_ics(cfg, conn) -> tuple[list[str], list[str]]:
    due_lines: list[str] = []
    for ev in canvas_ics.fetch(cfg.canvas_ics_url):
        if not ev["title"]:
            continue
        if not mark_seen(conn, "canvas_ics", ev["uid"]):
            continue
        _upsert_item(conn, ev["uid"], ev["course"], ev["title"], "assignment", ev["due_at"])
        when = (ev["due_at"] or "")[:10] or "no date"
        course = f" ({ev['course']})" if ev["course"] else ""
        due_lines.append((ev["due_at"] or "~", f"• {when} — {ev['title']}{course}"))
    conn.commit()
    return [line for _, line in sorted(due_lines, key=lambda x: x[0])], []


def _via_api(cfg, conn) -> tuple[list[str], list[str]]:
    todos = canvas.todo(cfg)
    upcoming = canvas.upcoming_events(cfg)
    course_list = canvas.courses(cfg)
    course_names = {str(c.get("id")): c.get("name", "?") for c in course_list}
    try:
        posts = canvas.announcements(cfg, list(course_names.keys()))
    except CanvasAuthError:
        posts = []

    due: list[tuple[str, str]] = []
    for t in todos:
        a = t.get("assignment", {}) or {}
        title = a.get("name", t.get("type", "todo"))
        uid = f"todo-{a.get('id', title)}"
        if not mark_seen(conn, "canvas_todo", uid):
            continue
        due_at = a.get("due_at", "") or ""
        _upsert_item(conn, uid, "", title, "assignment", due_at)
        due.append((due_at or "~", f"• {due_at[:10] or 'no date'} — {title}"))

    ann_lines: list[str] = []
    for p in posts:
        if not mark_seen(conn, "canvas_announcement", f"ann-{p.get('id')}"):
            continue
        title = p.get("title", "(untitled)")
        ann_lines.append(f"• {title}")
        if cfg.ingest:
            library.add_document(conn, cfg, "canvas", title, p.get("message", "") or "")
    conn.commit()
    return [line for _, line in sorted(due, key=lambda x: x[0])], ann_lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "canvas")
    conn = connect()

    try:
        if cfg.canvas_ics_url:
            source = "ics"
            due_lines, ann_lines = _via_ics(cfg, conn)
        elif cfg.canvas_token and cfg.canvas_base_url:
            source = "api"
            due_lines, ann_lines = _via_api(cfg, conn)
        else:
            print("no Canvas configured (set CANVAS_ICS_URL or CANVAS_TOKEN).")
            return
    except CanvasAuthError as exc:
        print(f"canvas auth error: {exc}")
        log_event("canvas", "auth_error", {"error": str(exc)})
        return

    if not due_lines and not ann_lines:
        print("canvas: nothing new.")
        return

    stamp = datetime.now(timezone.utc).strftime("%b %d")
    out = [f"**🎓 Canvas — {stamp}**"]
    if due_lines:
        out.append("\n__Due soon__")
        out.extend(due_lines)
    if ann_lines:
        out.append("\n__New announcements__")
        out.extend(ann_lines)
    digest = "\n".join(out)

    if args.dry_run:
        print(digest)
    else:
        chan.send(cfg, digest)
    log_event("canvas", "digest_sent",
              {"source": source, "due": len(due_lines), "announcements": len(ann_lines)})


if __name__ == "__main__":
    main()
