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


def _today_events(cfg, conn) -> list[dict]:
    """Today's events on Ernest's canonical calendar; empty if not configured."""
    from ernest import gcal
    from ernest.store import get_setting

    calendar_id = get_setting(conn, "gcal_calendar_id")
    account = cfg.calendar_account
    if not account:
        from ernest import mail

        account = next((n for p, n in mail.accounts(cfg)
                        if p == "gmail" and gcal.has_token(cfg, n)), None)
    if not calendar_id or not account:
        return []
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        return gcal.list_events(cfg, account, calendar_id, start.isoformat(), end.isoformat())
    except Exception:
        return []


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
    events = _today_events(cfg, conn)

    stamp = datetime.now(timezone.utc).strftime("%A, %b %d")
    out = [f"**🎩 Morning brief — {stamp}**"]
    facts = [f"Date: {stamp}."]
    w = weather.one_liner(cfg)
    if w:
        out.append(f"🌤️ {w}")
        facts.append(f"Weather: {w}")
    if events:
        out.append("\n__On your calendar today__")
        out.extend(f"• {e['start'][11:16] or 'all day'} — {e['title']}" for e in events)
        facts.append("On the calendar today:")
        facts.extend(f"- {e['start'][11:16] or 'all day'}: {e['title']}"
                     + (f" at {e['location']}" if e['location'] else "") for e in events)
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
    if not due and not counts:
        return ""  # nothing to report — stay silent (weather alone isn't news)
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
    if not by_action and not flagged:
        return ""  # nothing happened today — stay silent
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
    if not text:
        print(f"{args.mode}: nothing to report — staying quiet.")
        log_event("brief", f"{args.mode}_skipped_empty", {})
        return
    if args.dry_run:
        print(text)
    else:
        chan.send(cfg, text)
    log_event("brief", f"{args.mode}_sent", {"dry_run": args.dry_run})


if __name__ == "__main__":
    main()
