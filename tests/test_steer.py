"""Priority steering: DB-backed rules that merge into triage."""

from ernest import steer, triage
from ernest.config import Config
from ernest.store import connect


def _db(tmp_path):
    return connect(str(tmp_path / "t.db"))


def test_add_and_list_rules(tmp_path):
    conn = _db(tmp_path)
    assert steer.add(conn, "sender", "karli@example.com") is True
    assert steer.add(conn, "sender", "karli@example.com") is False   # dupe
    assert steer.add(conn, "keyword", "Henderson contract") is True
    senders, keywords = steer.priority_rules(conn)
    assert senders == ["karli@example.com"]
    assert keywords == ["Henderson contract"]


def test_remove_rule(tmp_path):
    conn = _db(tmp_path)
    steer.add(conn, "keyword", "newsletter")
    assert steer.remove(conn, "keyword", "NEWSLETTER") is True   # case-insensitive
    assert steer.remove(conn, "keyword", "newsletter") is False  # already gone
    assert steer.priority_rules(conn) == ([], [])


def test_priority_reason_uses_steer_rules():
    cfg = Config()  # no .env priority rules
    msg = {"sender": "Karli <karli@example.com>", "subject": "hi", "body_text": ""}
    assert triage.priority_reason(cfg, msg) is None
    assert triage.priority_reason(cfg, msg, ("karli@example.com",), ()) == "from karli@example.com"

    kw_msg = {"sender": "x@y.com", "subject": "re: Henderson contract", "body_text": ""}
    assert triage.priority_reason(cfg, kw_msg, (), ("Henderson contract",)) == 'mentions "Henderson contract"'
