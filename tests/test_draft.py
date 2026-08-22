"""Tests for reply drafting (no network: monkeypatch mail + model)."""

import dataclasses

from ernest import draft
from ernest.config import Config
from ernest.store import connect


def _cfg():
    return dataclasses.replace(Config(), accounts=("gmail:work",))


def test_voice_samples_cached(tmp_path, monkeypatch):
    conn = connect(str(tmp_path / "t.db"))
    calls = {"n": 0}

    def fake_sent(cfg, provider, account, max_results=12):
        calls["n"] += 1
        return [{"subject": "Re: proof", "body_text": "Sounds good — send it over. Quinton"}]

    monkeypatch.setattr("ernest.mail.sent", fake_sent)
    s1 = draft._voice_samples(_cfg(), conn, "gmail", "work")
    s2 = draft._voice_samples(_cfg(), conn, "gmail", "work")
    assert "send it over" in s1
    assert s1 == s2
    assert calls["n"] == 1  # second call hit the cache, no refetch


def test_draft_reply_uses_model(tmp_path, monkeypatch):
    conn = connect(str(tmp_path / "t.db"))
    monkeypatch.setattr("ernest.mail.sent", lambda *a, **k: [])
    captured = {}

    def fake_complete_text(cfg, model, system, user, max_tokens=600):
        captured["system"] = system
        captured["user"] = user
        return "Hi — thanks, that works. Quinton"

    monkeypatch.setattr("ernest.draft.complete_text", fake_complete_text)
    msg = {"sender": "vendor@x.com", "subject": "Availability?", "body_text": "Are you free Tue?"}
    out = draft.draft_reply(_cfg(), conn, "gmail", "work", msg)
    assert out == "Hi — thanks, that works. Quinton"
    assert "Are you free Tue?" in captured["user"]
    assert "untrusted data" in captured["system"]
