"""Mirror sync: create-new / skip-identical / update-changed / delete-vanished.

The gcal write calls are monkeypatched; we assert on the gcal_mirror bookkeeping
and which API calls fire.
"""

import os

import pytest

from ernest import gcal
from ernest.config import Config
from ernest.store import connect
from jobs import gcal_sync


@pytest.fixture()
def conn(tmp_path):
    return connect(os.path.join(tmp_path, "t.db"))


@pytest.fixture()
def patched(monkeypatch):
    calls = {"create": [], "update": [], "delete": []}
    monkeypatch.setattr(gcal, "create_event",
                        lambda cfg, a, c, ev: calls["create"].append(ev) or {"id": f"e{len(calls['create'])}"})
    monkeypatch.setattr(gcal, "update_event",
                        lambda cfg, a, c, eid, ev: calls["update"].append(eid) or {"id": eid})
    monkeypatch.setattr(gcal, "delete_event",
                        lambda cfg, a, c, eid: calls["delete"].append(eid))
    return calls


def _upsert(conn, counts, seen, key, title="Meet", start="2026-09-03T13:00", end="2026-09-03T14:00"):
    gcal_sync._upsert(Config(), conn, "cal1", "personal", key, title, start, end, "", seen, counts)


def test_new_event_creates_and_records(conn, patched):
    counts = {"created": 0, "updated": 0, "deleted": 0}
    seen = set()
    _upsert(conn, counts, seen, "gmail:work:1")
    conn.commit()
    assert counts["created"] == 1
    assert "gmail:work:1" in seen
    row = conn.execute("SELECT event_id FROM gcal_mirror WHERE source_key=?", ("gmail:work:1",)).fetchone()
    assert row["event_id"] == "e1"


def test_identical_event_is_skipped(conn, patched):
    counts = {"created": 0, "updated": 0, "deleted": 0}
    _upsert(conn, counts, set(), "gmail:work:1")
    conn.commit()
    _upsert(conn, counts, set(), "gmail:work:1")  # same content, second run
    assert counts["created"] == 1 and counts["updated"] == 0
    assert patched["update"] == []


def test_changed_event_updates(conn, patched):
    counts = {"created": 0, "updated": 0, "deleted": 0}
    _upsert(conn, counts, set(), "gmail:work:1", title="Meet")
    conn.commit()
    _upsert(conn, counts, set(), "gmail:work:1", title="Meet (moved)")
    assert counts["updated"] == 1
    assert patched["update"] == ["e1"]


def test_sweep_deletes_vanished(conn, patched):
    counts = {"created": 0, "updated": 0, "deleted": 0}
    _upsert(conn, counts, set(), "gmail:work:1")
    _upsert(conn, counts, set(), "gmail:work:2")
    conn.commit()
    # only :1 seen this run → :2 should be deleted from calendar + table
    seen = {"gmail:work:1"}
    gcal_sync._sweep_deleted(conn, "cal1", "personal", "gmail:work:", seen, counts,
                             lambda cal, eid: gcal.delete_event(Config(), "personal", cal, eid))
    conn.commit()
    assert counts["deleted"] == 1
    assert patched["delete"] == ["e2"]
    remaining = conn.execute("SELECT source_key FROM gcal_mirror").fetchall()
    assert [r["source_key"] for r in remaining] == ["gmail:work:1"]


def test_no_home_account_exits_quietly(conn, monkeypatch, capsys):
    # no gmail account has a gcal token → job prints guidance and returns
    monkeypatch.setattr(gcal_sync, "load", lambda: Config(accounts=("gmail:work",)))
    monkeypatch.setattr(gcal, "has_token", lambda cfg, a: False)
    monkeypatch.setattr(gcal_sync, "connect", lambda: conn)
    monkeypatch.setattr("sys.argv", ["gcal_sync"])
    gcal_sync.main()
    assert "no Google account" in capsys.readouterr().out
