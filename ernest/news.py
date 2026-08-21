"""News feeds — RSS in, plain dicts out. Read-only.

Google Alerts arrive as email and are rerouted by triage; this module handles
the RSS/Atom side. A feed that errors is skipped, never fatal.
"""

from __future__ import annotations

from html.parser import HTMLParser

from .audit import log_event

_SUMMARY_LIMIT = 500


class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _strip_html(raw: str) -> str:
    parser = _Stripper()
    try:
        parser.feed(raw or "")
    except Exception:
        return (raw or "")[:_SUMMARY_LIMIT]
    return parser.text()[:_SUMMARY_LIMIT]


def fetch(feed_urls: list[str]) -> list[dict]:
    import feedparser

    items: list[dict] = []
    for url in feed_urls:
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:
            log_event("news", "feed_failed", {"url": url, "error": str(exc)})
            continue
        if getattr(parsed, "bozo", 0) and not parsed.entries:
            log_event("news", "feed_failed", {"url": url, "error": "unparseable"})
            continue
        for entry in parsed.entries:
            items.append(
                {
                    "id": entry.get("id") or entry.get("link", ""),
                    "title": entry.get("title", "(untitled)"),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": _strip_html(entry.get("summary", "")),
                }
            )
    return items
