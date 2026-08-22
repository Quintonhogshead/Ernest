"""Google Calendar module — token paths, normalization, event bodies, fingerprints.

No network or google SDK needed: we test the pure helpers directly.
"""

import dataclasses

from ernest import gcal
from ernest.config import Config


def _cfg(tmp_path):
    return dataclasses.replace(Config(), google_credentials_dir=str(tmp_path))


def test_token_path_and_has_token(tmp_path):
    cfg = _cfg(tmp_path)
    assert gcal._token_path(cfg, "work").endswith("gcal_token_work.json")
    assert not gcal.has_token(cfg, "work")
    (tmp_path / "gcal_token_work.json").write_text("{}")
    assert gcal.has_token(cfg, "work")


def test_normalize_datetime_event():
    raw = {
        "id": "abc", "summary": "Launch call",
        "start": {"dateTime": "2026-09-03T13:00:00-05:00"},
        "end": {"dateTime": "2026-09-03T14:00:00-05:00"},
        "location": "Zoom", "updated": "2026-08-01T00:00:00Z",
    }
    n = gcal._normalize(raw)
    assert n["title"] == "Launch call"
    assert n["start"] == "2026-09-03T13:00:00-05:00"
    assert n["location"] == "Zoom"


def test_normalize_all_day_and_missing_title():
    n = gcal._normalize({"id": "x", "start": {"date": "2026-09-03"}, "end": {"date": "2026-09-04"}})
    assert n["title"] == "(untitled)"
    assert n["start"] == "2026-09-03"
    assert n["location"] == ""


def test_event_body_timed_vs_all_day():
    timed = gcal._event_body({"title": "T", "start": "2026-09-03T13:00:00-05:00",
                              "end": "2026-09-03T14:00:00-05:00", "location": "Zoom"})
    assert timed["start"] == {"dateTime": "2026-09-03T13:00:00-05:00"}
    assert timed["location"] == "Zoom"
    allday = gcal._event_body({"title": "T", "start": "2026-09-03", "end": "2026-09-04"})
    assert allday["start"] == {"date": "2026-09-03"}
    assert "location" not in allday


def test_normalize_carries_meet_and_attendees():
    raw = {
        "id": "e1", "summary": "Sync", "start": {"dateTime": "2026-09-03T13:00:00-05:00"},
        "end": {"dateTime": "2026-09-03T14:00:00-05:00"},
        "hangoutLink": "https://meet.google.com/abc-defg-hij",
        "conferenceData": {"entryPoints": [{"meetingCode": "abcdefghij"}]},
        "attendees": [{"email": "karli@x.com"}, {"email": "quinton@atmospherepress.com"},
                      {"displayName": "no email"}],
    }
    n = gcal._normalize(raw)
    assert n["meet_url"] == "https://meet.google.com/abc-defg-hij"
    assert n["meeting_code"] == "abcdefghij"
    assert n["attendees"] == ["karli@x.com", "quinton@atmospherepress.com"]


def test_meeting_code_falls_back_to_link():
    raw = {"hangoutLink": "https://meet.google.com/xyz-1234-abc"}
    assert gcal._meeting_code(raw) == "xyz-1234-abc"
    assert gcal._meeting_code({}) == ""


def test_fingerprint_stable_and_sensitive():
    a = gcal.fingerprint("Lunch", "2026-09-03T13:00", "2026-09-03T14:00", "Cafe")
    b = gcal.fingerprint("Lunch", "2026-09-03T13:00", "2026-09-03T14:00", "Cafe")
    c = gcal.fingerprint("Lunch", "2026-09-03T13:30", "2026-09-03T14:00", "Cafe")
    assert a == b
    assert a != c
