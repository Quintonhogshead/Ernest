"""Parse a Gmail Takeout .mbox export into plain message dicts (streaming).

Takeout gives one big .mbox per mailbox. This iterates it lazily so a multi-GB
file doesn't have to fit in memory, extracts the text body (prefer text/plain,
fall back to stripped HTML), and yields dicts the library can ingest.
"""

from __future__ import annotations

import mailbox
from email.header import decode_header, make_header

from .news import _strip_html

_BODY_LIMIT = 8000  # chars kept per message (chunk_text splits it further)


def _hdr(msg, name: str) -> str:
    raw = msg.get(name, "") or ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


def _decode_part(part) -> str:
    try:
        raw = part.get_payload(decode=True)
        if raw is None:
            return ""
        charset = part.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")
    except Exception:
        return ""


def _body(msg) -> str:
    if msg.is_multipart():
        plain, html = [], []
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                plain.append(_decode_part(part))
            elif ct == "text/html":
                html.append(_decode_part(part))
        if any(plain):
            return "\n".join(p for p in plain if p)
        return _strip_html("\n".join(h for h in html if h))
    payload = _decode_part(msg)
    if msg.get_content_type() == "text/html":
        return _strip_html(payload)
    return payload


def iter_messages(path: str, limit: int | None = None, skip: int = 0):
    """Yield {id, sender, subject, date, body_text} for each message."""
    mb = mailbox.mbox(path)
    n = 0
    for i, key in enumerate(mb.iterkeys()):
        if i < skip:
            continue
        try:
            msg = mb.get_message(key)
        except Exception:
            continue
        yield {
            "id": (msg.get("Message-ID", "") or f"mbox-{i}"),
            "sender": _hdr(msg, "From"),
            "subject": _hdr(msg, "Subject"),
            "date": msg.get("Date", ""),
            "body_text": (_body(msg) or "")[:_BODY_LIMIT],
        }
        n += 1
        if limit and n >= limit:
            break
