"""Tests for multi-provider mail account parsing."""

import dataclasses

import pytest

from ernest import mail
from ernest.config import Config
from ernest.mail import UnknownProvider


def _cfg(accounts):
    return dataclasses.replace(Config(), accounts=tuple(accounts))


def test_provider_prefixes_parse():
    cfg = _cfg(["gmail:work", "gmail:personal", "outlook:business", "outlook:school"])
    assert mail.accounts(cfg) == [
        ("gmail", "work"), ("gmail", "personal"),
        ("outlook", "business"), ("outlook", "school"),
    ]


def test_bare_name_defaults_to_gmail():
    assert mail.accounts(_cfg(["work"])) == [("gmail", "work")]


def test_whitespace_and_case_tolerated():
    assert mail.accounts(_cfg([" Outlook : Job "])) == [("outlook", "Job")]


def test_unknown_provider_raises():
    with pytest.raises(UnknownProvider):
        mail.accounts(_cfg(["yahoo:me"]))


def test_unread_dispatch_unknown_provider():
    with pytest.raises(UnknownProvider):
        mail.unread(Config(), "yahoo", "me")
