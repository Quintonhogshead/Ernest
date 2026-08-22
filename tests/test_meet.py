"""Meet module — token path + transcript assembly, with a faked API service."""

import dataclasses

from ernest import meet
from ernest.config import Config


def _cfg(tmp_path):
    return dataclasses.replace(Config(), google_credentials_dir=str(tmp_path))


def test_token_path_and_has_token(tmp_path):
    cfg = _cfg(tmp_path)
    assert meet._token_path(cfg, "work").endswith("gmeet_token_work.json")
    assert not meet.has_token(cfg, "work")
    (tmp_path / "gmeet_token_work.json").write_text("{}")
    assert meet.has_token(cfg, "work")


# ── a minimal fake of the googleapiclient chained builder ────────────────────

class _Req:
    def __init__(self, result):
        self._r = result

    def execute(self):
        return self._r


class _Entries:
    def __init__(self, entries):
        self._e = entries

    def list(self, parent=None, pageToken=None):
        return _Req({"transcriptEntries": self._e, "nextPageToken": None})


class _Transcripts:
    def __init__(self, transcripts, entries):
        self._t = transcripts
        self._entries = _Entries(entries)

    def list(self, parent=None, pageToken=None):
        return _Req({"transcripts": self._t})

    def entries(self):
        return self._entries


class _Participants:
    def get(self, name=None):
        return _Req({"signedinUser": {"displayName": "Karli"}})


class _ConfRecords:
    def __init__(self, transcripts, entries):
        self._tr = _Transcripts(transcripts, entries)
        self._p = _Participants()

    def transcripts(self):
        return self._tr

    def participants(self):
        return self._p


class _Svc:
    def __init__(self, transcripts, entries):
        self._cr = _ConfRecords(transcripts, entries)

    def conferenceRecords(self):
        return self._cr


def test_get_transcript_assembles_speaker_lines(monkeypatch):
    entries = [{"text": "Hello there", "participant": "p1"},
               {"text": "Let's ship it", "participant": "p1"}]
    svc = _Svc([{"name": "t1", "state": "FILE_GENERATED"}], entries)
    monkeypatch.setattr(meet, "_service", lambda cfg, a: svc)
    out = meet.get_transcript(Config(), "work", "rec1")
    assert out == "Karli: Hello there\nKarli: Let's ship it"


def test_get_transcript_none_when_not_generated(monkeypatch):
    svc = _Svc([{"name": "t1", "state": "STARTED"}], [])
    monkeypatch.setattr(meet, "_service", lambda cfg, a: svc)
    assert meet.get_transcript(Config(), "work", "rec1") is None


def test_get_transcript_none_when_no_transcripts(monkeypatch):
    svc = _Svc([], [])
    monkeypatch.setattr(meet, "_service", lambda cfg, a: svc)
    assert meet.get_transcript(Config(), "work", "rec1") is None
