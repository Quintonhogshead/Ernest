"""iMessage/SMS reader → triage digest. Read-only, macOS only.

Requires Full Disk Access. There is NO reply path in this codebase. Message text
is not ingested into the library by default (privacy); flip that decision
deliberately if you ever want it.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from ernest import chan, imessage, triage
from ernest.audit import log_event
from ernest.config import load
from ernest.guard import halt_if_paused
from ernest.imessage import IMessageError
from ernest.store import connect, mark_seen


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "imessage")
    conn = connect()

    try:
        msgs = imessage.recent(hours=args.hours)
    except IMessageError as exc:
        print(f"imessage: {exc}")
        log_event("imessage", "read_error", {"error": str(exc)})
        return

    from ernest import steer
    extra_senders, extra_keywords = steer.priority_rules(conn)
    lines, urgent = [], []
    new = 0
    for m in msgs:
        if m["is_from_me"]:
            continue
        if not mark_seen(conn, "imsg", m["rowid"]):
            continue
        new += 1
        result = triage.classify(cfg, m, kind="text")
        reason = triage.priority_reason(cfg, m, tuple(extra_senders), tuple(extra_keywords))
        if reason:
            result["urgent"] = True
        entry = f"• {m['sender']} — {result['summary']}"
        lines.append(entry)
        if result.get("urgent"):
            tag = "⭐ Priority (text)" if reason else "⚠️ (text)"
            urgent.append(f"{tag} {m['sender']}\n{result['summary']}" + (f"\n_{reason}_" if reason else ""))

    for u in urgent:
        if args.dry_run:
            print(u + "\n")
        else:
            chan.send(cfg, u)

    if not lines:
        print("imessage: nothing new.")
        return

    stamp = datetime.now(timezone.utc).strftime("%b %d %H:%M")
    digest = f"**💬 Texts — {stamp}**\n" + "\n".join(lines)
    if args.dry_run:
        print(digest)
    else:
        chan.send(cfg, digest)
    log_event("imessage", "digest_sent", {"new": new})


if __name__ == "__main__":
    main()
