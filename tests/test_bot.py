"""Tests for the interactive bot's pure command router."""

import ernest.llm as llm
from ernest.bot import classify, route
from ernest.config import Config


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


def test_event_prefixes():
    assert route("event lunch with Karli Tuesday 1pm") == ("event", "lunch with Karli Tuesday 1pm")
    assert route("add event dentist Thursday 9am") == ("event", "dentist Thursday 9am")
    assert route("schedule call with the printer friday") == ("event", "call with the printer friday")
    assert route("event: book launch Sept 3") == ("event", "book launch Sept 3")


def test_plain_english_calendar_add_routes_to_event():
    # Free-form add/move/cancel intent is promoted into the approval-gated
    # event flow (whole text passed through for extraction), not chat.
    for t in (
        "put dinner with Sam on my calendar Friday 7pm",
        "add lunch with Karli to my calendar Tuesday 1pm",
        "can you schedule a call with the printer friday",
        "pencil in a dentist appointment Thursday 9am",
        "move the book launch on my calendar to Sept 4",
        "draft an all-day calendar event for 1 Year with Hannah on September 5",
        "can you make a calendar event for my anniversary Sept 5",
    ):
        assert route(t) == ("event", t)


def test_calendar_questions_route_to_agenda():
    # Reading/checking the calendar routes to the read-only agenda command,
    # never to the write-draft flow.
    for t in (
        "agenda",
        "my calendar",
        "what's on my calendar today?",
        "when is my next meeting on the calendar",
        "am I free friday afternoon?",
        "show me my calendar for next week",
        "what do I have tomorrow",
    ):
        assert route(t)[0] == "agenda"


def test_nonclendar_freeform_still_chat():
    for t in ("what did we tell that author?", "hey, how's it going?",
              "summarize the Karli thread"):
        assert route(t)[0] == "chat"


def test_approve_deny():
    assert route("approve 3") == ("approve", "3")
    assert route("deny 5") == ("deny", "5")
    assert route("yes 7") == ("approve", "7")
    assert route("cancel 2") == ("deny", "2")


def test_meetings_and_search():
    assert route("meetings")[0] == "meetings"
    assert route("meeting the Karli sync") == ("meeting_search", "the Karli sync")
    assert route("recap Social Media Pro") == ("meeting_search", "Social Media Pro")
    # exact "meetings" must not be swallowed by the "meeting " prefix
    assert route("meetings")[1] == ""


def test_classify_maps_llm_intent(monkeypatch):
    # The LLM router turns free-form text into a dispatchable (intent, arg).
    monkeypatch.setattr(
        llm, "complete_json",
        lambda *a, **k: {"intent": "event", "argument": "dinner with Sam Friday 7pm"},
    )
    assert classify(Config(), "could you pop dinner with Sam on Friday at 7") == (
        "event", "dinner with Sam Friday 7pm")


def test_classify_chat_keeps_original_text(monkeypatch):
    monkeypatch.setattr(llm, "complete_json",
                        lambda *a, **k: {"intent": "chat", "argument": "ignored"})
    assert classify(Config(), "hey there") == ("chat", "hey there")


def test_classify_falls_back_to_chat_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no api key")
    monkeypatch.setattr(llm, "complete_json", boom)
    assert classify(Config(), "whatever") == ("chat", "whatever")


def test_classify_rejects_unknown_intent(monkeypatch):
    monkeypatch.setattr(llm, "complete_json",
                        lambda *a, **k: {"intent": "launch_missiles", "argument": "x"})
    assert classify(Config(), "do the thing") == ("chat", "do the thing")
