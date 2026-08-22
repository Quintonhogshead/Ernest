"""Calendar mirror: work + personal Google Calendar + Canvas due-dates → one
canonical "Ernest" calendar, which Apple Calendar (or anything else) can
subscribe to read-only.

This is a pure copy, not a decision — nothing here needs approval. It never
touches your real calendars; it only ever reads from them and writes to the
one calendar Ernest itself owns (created on first run). New commitments
(Quinton asking Ernest to add something) go through ernest/gcal_actions.py's
propose/approve flow in the Discord bot instead — see ernest/bot.py.

  python -m jobs.gcal_sync --dry-run
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from ernest import chan, gcal, mail
from ernest.audit import log_event
from ernest.config import load
from ernest.gcal import GcalAuthError
from ernest.guard import halt_if_paused
from ernest.store import connect, get_setting, set_setting

_CAL_ID_KEY = "gcal_calendar_id"
_SUBSCRIBE_NOTE = (
    "📅 I made you a calendar — it aggregates your work + personal Google "
    "Calendars and Canvas due-dates, and I'll keep it updated automatically.\n\n"
    "To see it in Apple Calendar: open Google Calendar on the web → find "
    "\"Ernest\" under My Calendars → Settings and sharing → copy the "
    "\"Secret address in iCal format\" → in Apple Calendar, Settings → "
    "Accounts → Add Subscribed Calendar → paste it in."
)


def _home_account(cfg) -> str | None:
    if cfg.calendar_account:
        return cfg.calendar_account
    for provider, account in mail.accounts(cfg):
        if provider == "gmail" and gcal.has_token(cfg, account):
            return account
    return None


def _resolve_calendar(cfg, conn, account: str, dry_run: bool) -> str:
    calendar_id = get_setting(conn, _CAL_ID_KEY)
    if calendar_id:
        return calendar_id
    calendar_id = gcal.get_or_create_calendar(cfg, account)
    set_setting(conn, _CAL_ID_KEY, calendar_id)
    log_event("gcal", "calendar_created", {"account": account, "calendar_id": calendar_id})
    if not dry_run:
        chan.send(cfg, _SUBSCRIBE_NOTE)
    return calendar_id


def _upsert(cfg, conn, calendar_id: str, account: str, source_key: str,
            title: str, start: str, end: str, location: str,
            seen: set[str], counts: dict[str, int]) -> None:
    seen.add(source_key)
    fp = gcal.fingerprint(title, start, end, location)
    row = conn.execute(
        "SELECT event_id, fingerprint FROM gcal_mirror WHERE source_key = ?", (source_key,)
    ).fetchone()
    event = {"title": title, "start": start, "end": end, "location": location}
    now = datetime.now(timezone.utc).isoformat()
    if row is None:
        created = gcal.create_event(cfg, account, calendar_id, event)
        conn.execute(
            "INSERT INTO gcal_mirror (source_key, event_id, fingerprint, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (source_key, created["id"], fp, now),
        )
        counts["created"] += 1
    elif row["fingerprint"] != fp:
        gcal.update_event(cfg, account, calendar_id, row["event_id"], event)
        conn.execute(
            "UPDATE gcal_mirror SET fingerprint = ?, updated_at = ? WHERE source_key = ?",
            (fp, now, source_key),
        )
        counts["updated"] += 1


def _sweep_deleted(conn, calendar_id: str, account: str, prefix: str, seen: set[str],
                    counts: dict[str, int], do_delete) -> None:
    rows = conn.execute(
        "SELECT source_key, event_id FROM gcal_mirror WHERE source_key LIKE ?",
        (f"{prefix}%",),
    ).fetchall()
    for row in rows:
        if row["source_key"] in seen:
            continue
        do_delete(calendar_id, row["event_id"])
        conn.execute("DELETE FROM gcal_mirror WHERE source_key = ?", (row["source_key"],))
        counts["deleted"] += 1


def _sync_google_sources(cfg, conn, calendar_id: str, home_account: str,
                          counts: dict[str, int]) -> None:
    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=cfg.gcal_sync_days)).isoformat()
    for provider, account in mail.accounts(cfg):
        if provider != "gmail" or not gcal.has_token(cfg, account):
            continue
        prefix = f"gmail:{account}:"
        seen: set[str] = set()
        try:
            events = gcal.list_events(cfg, account, "primary", time_min, time_max)
        except GcalAuthError as exc:
            log_event("gcal", "auth_error", {"account": account, "error": str(exc)})
            continue
        for ev in events:
            source_key = f"{prefix}{ev['id']}"
            _upsert(cfg, conn, calendar_id, home_account, source_key,
                   ev["title"], ev["start"], ev["end"], ev["location"], seen, counts)
        _sweep_deleted(conn, calendar_id, home_account, prefix, seen, counts,
                      lambda cal, eid: gcal.delete_event(cfg, home_account, cal, eid))
        conn.commit()


def _sync_canvas(cfg, conn, calendar_id: str, home_account: str,
                  counts: dict[str, int]) -> None:
    prefix = "canvas:"
    seen: set[str] = set()
    items = conn.execute(
        "SELECT item_id, title, course, due_at FROM canvas_items WHERE due_at != ''"
    ).fetchall()
    for item in items:
        due = item["due_at"]
        try:
            start_dt = datetime.fromisoformat(due.replace("Z", "+00:00"))
        except ValueError:
            continue
        end_dt = start_dt + timedelta(minutes=30)
        title = f"Due: {item['title']}" + (f" ({item['course']})" if item["course"] else "")
        source_key = f"{prefix}{item['item_id']}"
        _upsert(cfg, conn, calendar_id, home_account, source_key,
               title, start_dt.isoformat(), end_dt.isoformat(), "", seen, counts)
    _sweep_deleted(conn, calendar_id, home_account, prefix, seen, counts,
                  lambda cal, eid: gcal.delete_event(cfg, home_account, cal, eid))
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = load()
    halt_if_paused(cfg, "gcal")
    conn = connect()

    home_account = _home_account(cfg)
    if not home_account:
        print("no Google account has calendar access — run "
              "scripts/authorize.py gcal <account>.")
        return

    if args.dry_run:
        print(f"would sync using home account: {home_account}")
        return

    calendar_id = _resolve_calendar(cfg, conn, home_account, args.dry_run)
    counts = {"created": 0, "updated": 0, "deleted": 0}
    _sync_google_sources(cfg, conn, calendar_id, home_account, counts)
    _sync_canvas(cfg, conn, calendar_id, home_account, counts)
    log_event("gcal", "synced", counts)
    print(f"gcal sync: {counts}")


if __name__ == "__main__":
    main()
