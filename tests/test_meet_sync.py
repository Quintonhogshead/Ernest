"""meet_sync: transcript → summary/action-items → meetings row + library ingest,
with dedup and graceful skip when no transcript is ready."""

import json
import os

import pytest

from ernest import gcal, library, meet, voice
from ernest.config import Config
from ernest.store import connect
from jobs import meet_sync


@pytest.fixture()
def conn(tmp_path):
    return connect(os.path.join(tmp_path, "t.db"))


@pytest.fixture()
def wired(monkeypatch):
    sent = []
    monkeypatch.setattr(gcal, "has_token", lambda cfg, a: False)  # skip correlation
    monkeypatch.setattr(meet, "list_participants", lambda cfg, a, cid: ["Karli"])
    monkeypatch.setattr(meet_sync, "complete_json",
                        lambda *a, **k: {"summary": "Discussed the launch.",
                                         "action_items": ["send the copy"]})
    monkeypatch.setattr(voice, "compose", lambda cfg, i, f, fb: "MSG")
    monkeypatch.setattr(meet_sync.chan, "send", lambda cfg, text: sent.append(text))
    ingested = []
    monkeypatch.setattr(library, "add_document",
                        lambda conn, cfg, source, title, text: ingested.append(source))
    return sent, ingested


_REC = {"name": "conf/1", "meeting_code": "abc", "start": "2026-08-20T15:00:00Z",
        "end": "2026-08-20T15:30:00Z"}


def test_ingests_transcript_and_records(conn, wired, monkeypatch):
    sent, ingested = wired
    monkeypatch.setattr(meet, "get_transcript", lambda cfg, a, cid: "Karli: hi\nQ: ok")
    assert meet_sync._process_record(Config(), conn, "work", _REC, False) is True
    row = conn.execute("SELECT * FROM meetings WHERE conference_id='conf/1'").fetchone()
    assert row["transcript_ingested"] == 1
    assert json.loads(row["action_items"]) == ["send the copy"]
    assert ingested == ["meeting:conf/1"]
    assert sent == ["MSG"]


def test_second_run_is_deduped(conn, wired, monkeypatch):
    monkeypatch.setattr(meet, "get_transcript", lambda cfg, a, cid: "Karli: hi")
    meet_sync._process_record(Config(), conn, "work", _REC, False)
    assert meet_sync._process_record(Config(), conn, "work", _REC, False) is False


def test_no_transcript_leaves_stub_no_ingest(conn, wired, monkeypatch):
    sent, ingested = wired
    monkeypatch.setattr(meet, "get_transcript", lambda cfg, a, cid: None)
    assert meet_sync._process_record(Config(), conn, "work", _REC, False) is False
    row = conn.execute("SELECT transcript_ingested FROM meetings WHERE conference_id='conf/1'").fetchone()
    assert row["transcript_ingested"] == 0
    assert ingested == [] and sent == []


def test_title_falls_back_to_date():
    assert meet_sync._title_for(_REC, None) == "Meeting on 2026-08-20 15:00"
    assert meet_sync._title_for(_REC, {"title": "Launch sync"}) == "Launch sync"
