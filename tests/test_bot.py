"""Tests for the interactive bot's pure command router."""

from ernest.bot import route


def test_help_variants():
    for t in ("help", "?", "Commands", "/help"):
        assert route(t)[0] == "help"


def test_status():
    assert route("status")[0] == "status"


def test_ask_prefixes():
    assert route("ask what is due friday") == ("ask", "what is due friday")
    assert route("ask: the karli meeting") == ("ask", "the karli meeting")
    assert route("? quick question") == ("ask", "quick question")


def test_research():
    assert route("research audiobook distributors") == ("research", "audiobook distributors")
    assert route("research: indie presses") == ("research", "indie presses")


def test_freeform_becomes_ask():
    assert route("what did we tell that author?") == ("ask", "what did we tell that author?")


def test_empty_is_help():
    assert route("")[0] == "help"
    assert route("   ")[0] == "help"
