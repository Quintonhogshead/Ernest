"""Approval queue: propose → approve/deny, with gcal writes monkeypatched.

Verifies the safety property that nothing calls the calendar API until approved.
"""

import os

import pytest

from ernest import gcal, gcal_actions
from ernest.config import Config
from ernest.store import connect


@pytest.fixture()
def conn(tmp_path):
    return connect(os.path.join(tmp_path, "t.db"))


def _payload():
    return {"account": "personal", "calendar_id": "cal1",
            "event": {"title": "Lunch", "start": "2026-09-03T13:00:00-05:00",
                      "end": "2026-09-03T14:00:00-05:00"}}


def test_propose_stores_pending(conn):
    aid = gcal_actions.propose(conn, "gcal_create", _payload(), "add Lunch")
    row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (aid,)).fetchone()
    assert row["status"] == "pending"
    assert row["description"] == "add Lunch"


def test_approve_executes_and_marks_done(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(gcal, "create_event",
                        lambda cfg, acct, cal, ev: calls.append((acct, cal, ev)) or {"id": "e1"})
    aid = gcal_actions.propose(conn, "gcal_create", _payload(), "add Lunch")
    msg = gcal_actions.execute(Config(), conn, aid)
    assert len(calls) == 1 and calls[0][0] == "personal"
    assert "Done" in msg
    assert conn.execute("SELECT status FROM pending_actions WHERE id=?", (aid,)).fetchone()[0] == "executed"


def test_deny_never_calls_api(conn, monkeypatch):
    monkeypatch.setattr(gcal, "create_event",
                        lambda *a, **k: pytest.fail("must not write on deny"))
    aid = gcal_actions.propose(conn, "gcal_create", _payload(), "add Lunch")
    msg = gcal_actions.deny(conn, aid)
    assert "won't" in msg
    assert conn.execute("SELECT status FROM pending_actions WHERE id=?", (aid,)).fetchone()[0] == "denied"


def test_double_approve_is_noop(conn, monkeypatch):
    monkeypatch.setattr(gcal, "create_event", lambda *a, **k: {"id": "e1"})
    aid = gcal_actions.propose(conn, "gcal_create", _payload(), "add Lunch")
    gcal_actions.execute(Config(), conn, aid)
    again = gcal_actions.execute(Config(), conn, aid)  # already executed → not pending
    assert "No pending action" in again


def test_execute_failure_marks_failed(conn, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("api down")
    monkeypatch.setattr(gcal, "create_event", boom)
    aid = gcal_actions.propose(conn, "gcal_create", _payload(), "add Lunch")
    msg = gcal_actions.execute(Config(), conn, aid)
    assert "Couldn't" in msg
    assert conn.execute("SELECT status FROM pending_actions WHERE id=?", (aid,)).fetchone()[0] == "failed"
