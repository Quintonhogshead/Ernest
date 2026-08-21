"""Canvas poller → Discord digest. Read-only.

Fetches to-dos, upcoming events, and recent announcements; surfaces only unseen
items; ingests new announcements into the library.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ernest import canvas, chan, library
from ernest.audit import log_event
from ernest.canvas import CanvasAuthError
from ernest.config import load
from ernest.guard import halt_if_paused
from ernest.store import connect, mark_seen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "canvas")
    conn = connect()

    try:
        todos = canvas.todo(cfg)
        upcoming = canvas.upcoming_events(cfg)
        course_list = canvas.courses(cfg)
    except CanvasAuthError as exc:
        print(f"canvas auth error: {exc}")
        log_event("canvas", "auth_error", {"error": str(exc)})
        return

    course_names = {str(c.get("id")): c.get("name", "?") for c in course_list}
    course_ids = list(course_names.keys())
    try:
        posts = canvas.announcements(cfg, course_ids)
    except CanvasAuthError:
        posts = []

    due_lines, ann_lines = [], []

    for item in upcoming:
        cid = str(item.get("context_code", "")).replace("course_", "")
        title = item.get("title", "(untitled)")
        ext_id = f"up-{item.get('id', title)}"
        if not mark_seen(conn, "canvas_upcoming", ext_id):
            continue
        when = item.get("start_at", "") or ""
        due_lines.append((when, f"• {when[:10]} — {title} ({course_names.get(cid, '')})"))

    for t in todos:
        assignment = t.get("assignment", {}) or {}
        title = assignment.get("name", t.get("type", "todo"))
        ext_id = f"todo-{assignment.get('id', title)}"
        if not mark_seen(conn, "canvas_todo", ext_id):
            continue
        due = assignment.get("due_at", "") or ""
        due_lines.append((due, f"• {due[:10] or 'no date'} — {title}"))

    for p in posts:
        ext_id = f"ann-{p.get('id')}"
        if not mark_seen(conn, "canvas_announcement", ext_id):
            continue
        title = p.get("title", "(untitled)")
        body = (p.get("message", "") or "")[:300]
        ann_lines.append(f"• {title}")
        if cfg.ingest:
            library.add_document(conn, cfg, "canvas", title, p.get("message", "") or "")

    if not due_lines and not ann_lines:
        print("canvas: nothing new.")
        return

    stamp = datetime.now(timezone.utc).strftime("%b %d")
    out = [f"**🎓 Canvas — {stamp}**"]
    if due_lines:
        out.append("\n__Due soon__")
        out.extend(line for _, line in sorted(due_lines, key=lambda x: x[0] or "~"))
    if ann_lines:
        out.append("\n__New announcements__")
        out.extend(ann_lines)
    digest = "\n".join(out)

    if args.dry_run:
        print(digest)
    else:
        chan.send(cfg, digest)
    log_event("canvas", "digest_sent",
              {"due": len(due_lines), "announcements": len(ann_lines)})


if __name__ == "__main__":
    main()
