"""meet_reminder: attendee-matched recap + upcoming-window selection."""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from ernest import gcal, mail
from ernest.config import Config
from ernest.store import connect
from jobs import meet_reminder


@pytest.fixture()
def conn(tmp_path):
    return connect(os.path.join(tmp_path, "t.db"))


def _insert_meeting(conn, cid, attendees, summary, actions, start="2026-08-01T10:00:00Z"):
    conn.execute(
        "INSERT INTO meetings (conference_id, account, title, start_at, attendees, "
        "summary, action_items, transcript_ingested, processed_at) "
        "VALUES (?, 'work', 'Prev', ?, ?, ?, ?, 1, ?)",
        (cid, start, json.dumps(attendees), summary, json.dumps(actions), start),
    )
    conn.commit()


def test_last_meeting_matches_on_shared_attendee(conn):
    _insert_meeting(conn, "c1", ["karli@x.com"], "old", [], start="2026-07-01T10:00:00Z")
    _insert_meeting(conn, "c2", ["karli@x.com", "bob@x.com"], "newer", ["ship it"],
                    start="2026-08-01T10:00:00Z")
    row = meet_reminder._last_meeting_with(conn, ["karli@x.com"])
    assert row["summary"] == "newer"  # most recent wins


def test_last_meeting_none_when_no_overlap(conn):
    _insert_meeting(conn, "c1", ["karli@x.com"], "old", [])
    assert meet_reminder._last_meeting_with(conn, ["stranger@x.com"]) is None
    assert meet_reminder._last_meeting_with(conn, []) is None


def test_recap_includes_prior_summary_and_actions(conn):
    _insert_meeting(conn, "c2", ["karli@x.com"], "Talked Social Media Pro", ["send copy"])
    event = {"title": "Karli sync", "attendees": ["karli@x.com"], "start": "..."}
    facts, fallback = meet_reminder._recap(Config(), conn, event)
    assert "Social Media Pro" in facts
    assert "send copy" in facts


def test_upcoming_window_filters_to_meet_events_near_lead(conn, monkeypatch):
    now = datetime.now(timezone.utc)
    at_ten = (now + timedelta(minutes=10)).isoformat()
    at_hour = (now + timedelta(minutes=60)).isoformat()
    events = [
        {"id": "a", "title": "Meet soon", "meet_url": "https://meet.google.com/x",
         "start": at_ten, "attendees": []},
        {"id": "b", "title": "No meet link", "meet_url": "", "start": at_ten, "attendees": []},
        {"id": "c", "title": "Meet later", "meet_url": "https://meet.google.com/y",
         "start": at_hour, "attendees": []},
    ]
    monkeypatch.setattr(mail, "accounts", lambda cfg: [("gmail", "work")])
    monkeypatch.setattr(gcal, "has_token", lambda cfg, a: True)
    monkeypatch.setattr(gcal, "list_events", lambda cfg, a, cal, lo, hi: events)
    out = meet_reminder._upcoming_meet_events(Config(), 10)
    ids = {e["id"] for e in out}
    assert ids == {"a"}  # 'b' has no meet_url, 'c' is an hour out
