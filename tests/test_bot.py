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


def test_freeform_becomes_chat():
    assert route("what did we tell that author?") == ("chat", "what did we tell that author?")
    assert route("hey, how's it going?") == ("chat", "hey, how's it going?")


def test_ask_stays_library_grounded():
    # explicit ask is distinct from free-form chat
    assert route("ask the karli meeting")[0] == "ask"


def test_reset():
    for t in ("reset", "new", "clear", "/reset"):
        assert route(t)[0] == "reset"


def test_remember():
    assert route("remember I prefer morning meetings") == ("remember", "I prefer morning meetings")
    assert route("remember that the venue deposit is $500") == ("remember", "the venue deposit is $500")
    assert route("note: call the florist") == ("remember", "call the florist")


def test_notes_listing():
    for t in ("notes", "my notes", "/notes"):
        assert route(t)[0] == "notes"


def test_empty_is_help():
    assert route("")[0] == "help"
    assert route("   ")[0] == "help"
