"""Tests for the token-free Canvas calendar-feed (ICS) parser."""

from ernest.canvas_ics import parse_ics

SAMPLE = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:event-assignment-101@ucf.instructure.com
DTSTART:20260901T235900Z
SUMMARY:Essay 1 draft [ENG 1101]
DESCRIPTION:Submit via Canvas
END:VEVENT
BEGIN:VEVENT
UID:event-assignment-102@ucf.instructure.com
DTSTART;VALUE=DATE:20260905
SUMMARY:Quiz 2\\, chapters 3-4 [PHY 2048]
END:VEVENT
END:VCALENDAR
"""


def test_parses_events_titles_courses_dates():
    events = parse_ics(SAMPLE)
    assert len(events) == 2
    e1 = events[0]
    assert e1["title"] == "Essay 1 draft [ENG 1101]"
    assert e1["course"] == "ENG 1101"
    assert e1["due_at"].startswith("2026-09-01T23:59:00")


def test_unescapes_commas_and_parses_date_only():
    e2 = parse_ics(SAMPLE)[1]
    assert "Quiz 2, chapters 3-4" in e2["title"]
    assert e2["course"] == "PHY 2048"
    assert e2["due_at"].startswith("2026-09-05")


def test_line_folding_is_joined():
    folded = (
        "BEGIN:VEVENT\nUID:x\nDTSTART:20260101T120000Z\n"
        "SUMMARY:A very long assignment tit\n le [CS 101]\nEND:VEVENT\n"
    )
    e = parse_ics(folded)[0]
    assert e["title"] == "A very long assignment title [CS 101]"


def test_empty_input():
    assert parse_ics("") == []
