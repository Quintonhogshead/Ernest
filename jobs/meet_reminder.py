"""Pre-meeting recap: ~10 min before a Google Meet, DM Quinton who he's meeting,
what was discussed last time with them, and the action items from that meeting.

Runs every 5 minutes; picks up events whose start falls in a short window around
the configured lead time, and dedups so each meeting is only flagged once.

  python -m jobs.meet_reminder --dry-run
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone

from ernest import chan, gcal, library, mail, voice
from ernest.audit import log_event
from ernest.config import load
from ernest.gcal import GcalAuthError
from ernest.guard import halt_if_paused
from ernest.store import connect, mark_seen


def _upcoming_meet_events(cfg, lead: int) -> list[dict]:
    """Meet events starting within ~[lead-2, lead+3] minutes from now."""
    now = datetime.now(timezone.utc)
    lo = now.isoformat()
    hi = (now + timedelta(minutes=lead + 5)).isoformat()
    out: list[dict] = []
    for provider, account in mail.accounts(cfg):
        if provider != "gmail" or not gcal.has_token(cfg, account):
            continue
        try:
            events = gcal.list_events(cfg, account, "primary", lo, hi)
        except GcalAuthError:
            continue
        for e in events:
            if not e.get("meet_url"):
                continue
            try:
                start = datetime.fromisoformat((e["start"] or "").replace("Z", "+00:00"))
            except ValueError:
                continue
            mins = (start - now).total_seconds() / 60
            if lead - 2 <= mins <= lead + 3:
                out.append(e)
    return out


def _last_meeting_with(conn, attendees: list[str]) -> dict | None:
    """Most recent past meeting sharing at least one attendee with ``attendees``."""
    want = {a.lower() for a in attendees if a}
    if not want:
        return None
    rows = conn.execute(
        "SELECT title, start_at, summary, action_items, attendees FROM meetings "
        "WHERE transcript_ingested = 1 ORDER BY start_at DESC"
    ).fetchall()
    for row in rows:
        try:
            past = {a.lower() for a in json.loads(row["attendees"] or "[]")}
        except json.JSONDecodeError:
            past = set()
        if want & past:
            return row
    return None


def _recap(cfg, conn, event: dict) -> tuple[str, str]:
    """Build (facts, fallback) for the recap message."""
    title = event.get("title") or "your meeting"
    who = ", ".join(event.get("attendees", [])) or "the attendees"
    facts = [f"Upcoming in ~{cfg.meet_reminder_lead_min} minutes: {title}.",
             f"With: {who}."]
    fallback_lines = [f"**⏰ {title}** starts in ~{cfg.meet_reminder_lead_min} min — with {who}."]

    last = _last_meeting_with(conn, event.get("attendees", []))
    if last:
        facts.append(f"Last time with them ({(last['start_at'] or '')[:10]}): {last['summary']}")
        fallback_lines.append(f"\nLast time: {last['summary']}")
        try:
            items = json.loads(last["action_items"] or "[]")
        except json.JSONDecodeError:
            items = []
        if items:
            facts.append("Action items from that meeting:")
            facts.extend(f"- {a}" for a in items)
            fallback_lines.append("__From last time__\n" + "\n".join(f"• {a}" for a in items))
    else:
        # No prior meeting with these people — fall back to library context.
        try:
            hits = [h for h in library.search(conn, cfg, f"{title} {who}", k=3)
                    if h["source"].startswith("meeting:")]
        except Exception:
            hits = []
        if hits:
            facts.append("Possibly relevant from past meetings:")
            facts.extend(f"- {h['chunk'][:200]}" for h in hits)

    return "\n".join(facts), "\n".join(fallback_lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "meet_reminder")
    conn = connect()

    sent = 0
    for event in _upcoming_meet_events(cfg, cfg.meet_reminder_lead_min):
        facts, fallback = _recap(cfg, conn, event)
        msg = voice.compose(
            cfg, "Give Quinton a heads-up about this meeting starting soon — who "
            "it's with and what to remember from last time.", facts, fallback)
        if args.dry_run:
            print(msg + "\n")  # don't consume the dedup gate while previewing
            continue
        if not mark_seen(conn, "meet_reminder", event["id"]):
            continue  # already reminded about this meeting
        chan.send(cfg, msg)
        sent += 1
        log_event("meet_reminder", "sent", {"event": event["id"]})

    print(f"meet reminder: {sent} sent")


if __name__ == "__main__":
    main()
