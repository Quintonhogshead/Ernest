"""Daily briefs.

  python -m jobs.brief morning   → calendar-of-the-day feel: Canvas due <=72h,
                                    today's triage counts, weather.
  python -m jobs.brief evening   → what Ernest did today (from the audit log)
                                    plus anything urgent/needs_reply.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from ernest import chan, voice, weather
from ernest.audit import log_event, read_events
from ernest.config import load
from ernest.guard import halt_if_paused
from ernest.store import connect


def _today_start_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def morning(cfg) -> str:
    conn = connect()
    horizon = (datetime.now(timezone.utc) + timedelta(hours=72)).isoformat()
    due = conn.execute(
        "SELECT title, course, due_at FROM canvas_items "
        "WHERE due_at != '' AND due_at <= ? ORDER BY due_at", (horizon,)
    ).fetchall()
    today = _today_start_iso()
    counts = conn.execute(
        "SELECT category, COUNT(*) n FROM messages WHERE triaged_at >= ? "
        "GROUP BY category", (today,)
    ).fetchall()

    stamp = datetime.now(timezone.utc).strftime("%A, %b %d")
    out = [f"**🎩 Morning brief — {stamp}**"]
    facts = [f"Date: {stamp}."]
    w = weather.one_liner(cfg)
    if w:
        out.append(f"🌤️ {w}")
        facts.append(f"Weather: {w}")
    if due:
        out.append("\n__Due within 72h__")
        out.extend(f"• {d['due_at'][:10]} — {d['title']} ({d['course'] or ''})" for d in due)
        facts.append("Coursework due within 72h:")
        facts.extend(f"- {d['due_at'][:10]}: {d['title']} ({d['course'] or 'course n/a'})"
                     for d in due)
    if counts:
        out.append("\n__Unread, by type__")
        out.extend(f"• {c['category']}: {c['n']}" for c in counts)
        facts.append("Today's unread mail by category: "
                     + ", ".join(f"{c['n']} {c['category']}" for c in counts))
    if len(out) == 1:
        out.append("_Quiet start — nothing flagged._")
        facts.append("Nothing is flagged — a quiet start.")
    return voice.compose(
        cfg,
        f"Write Quinton's morning brief for {stamp} — his day at a glance.",
        "\n".join(facts), "\n".join(out),
    )


def evening(cfg) -> str:
    events = read_events(_today_start_iso())
    by_action: dict[str, int] = {}
    for e in events:
        key = f"{e['job']}.{e['action']}"
        by_action[key] = by_action.get(key, 0) + 1

    conn = connect()
    today = _today_start_iso()
    flagged = conn.execute(
        "SELECT account, sender, summary, category FROM messages "
        "WHERE triaged_at >= ? AND category IN ('urgent','needs_reply') "
        "ORDER BY urgent DESC", (today,)
    ).fetchall()

    stamp = datetime.now(timezone.utc).strftime("%A, %b %d")
    out = [f"**🌙 Evening wrap — {stamp}**"]
    facts = [f"Date: {stamp}."]
    if by_action:
        out.append("\n__What I did today__")
        out.extend(f"• {k}: {v}" for k, v in sorted(by_action.items()))
        facts.append("What I handled today (job.action: count): "
                     + ", ".join(f"{k} {v}" for k, v in sorted(by_action.items())))
    if flagged:
        out.append("\n__Still wants you__")
        out.extend(f"• [{f['account']}] {f['sender'][:35]} — {f['summary']}" for f in flagged)
        facts.append("Still needs your attention:")
        facts.extend(f"- [{f['account']}] {f['sender'][:40]}: {f['summary']} "
                     f"({f['category']})" for f in flagged)
    if len(out) == 1:
        out.append("_Nothing logged today._")
        facts.append("Nothing was logged today.")
    return voice.compose(
        cfg,
        f"Write Quinton's evening wrap for {stamp} — what you handled and what "
        "still needs him.",
        "\n".join(facts), "\n".join(out),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["morning", "evening"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "brief")
    text = morning(cfg) if args.mode == "morning" else evening(cfg)
    if args.dry_run:
        print(text)
    else:
        chan.send(cfg, text)
    log_event("brief", f"{args.mode}_sent", {"dry_run": args.dry_run})


if __name__ == "__main__":
    main()
