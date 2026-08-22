"""Tests for the always-ping priority matcher."""

import dataclasses

from ernest.config import Config
from ernest.triage import priority_reason


def _cfg(senders=(), keywords=()):
    return dataclasses.replace(Config(), priority_senders=tuple(senders),
                               priority_keywords=tuple(keywords))


def test_no_rules_never_priority():
    msg = {"sender": "a@b.com", "subject": "hi", "body_text": "urgent contract"}
    assert priority_reason(_cfg(), msg) is None


def test_sender_full_address_match():
    cfg = _cfg(senders=["boss@company.com"])
    msg = {"sender": "Boss <boss@company.com>", "subject": "x", "body_text": ""}
    assert priority_reason(cfg, msg) == "from boss@company.com"


def test_sender_domain_match():
    cfg = _cfg(senders=["@bigclient.com"])
    msg = {"sender": "anyone@bigclient.com", "subject": "x", "body_text": ""}
    assert priority_reason(cfg, msg).startswith("from @bigclient.com")


def test_keyword_in_subject_or_body():
    cfg = _cfg(keywords=["contract"])
    assert priority_reason(cfg, {"sender": "x", "subject": "New CONTRACT", "body_text": ""})
    assert priority_reason(cfg, {"sender": "x", "subject": "hi", "body_text": "the contract is attached"})


def test_keyword_no_match():
    cfg = _cfg(keywords=["invoice"])
    assert priority_reason(cfg, {"sender": "x", "subject": "lunch?", "body_text": "no"}) is None


def test_works_for_texts_too():
    cfg = _cfg(keywords=["911"])
    assert priority_reason(cfg, {"sender": "mom", "text": "call me 911"})
