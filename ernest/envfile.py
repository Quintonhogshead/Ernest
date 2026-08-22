"""Read and update a .env file in place, preserving comments and order.

Used by the local dashboard. Secret values are never logged or returned to the
browser — callers ask ``is_set()`` (a bool), and only write new values in.
"""

from __future__ import annotations

import os
import re

# Canonical fields the dashboard manages, grouped for the UI.
# (key, label, group, secret, placeholder)
FIELDS: list[tuple[str, str, str, bool, str]] = [
    ("ERNEST_TRIAGE_MODEL", "Triage model", "Models", False, "anthropic:claude-haiku-4-5"),
    ("ERNEST_ASK_MODEL", "Ask model", "Models", False, "anthropic:claude-sonnet-5"),
    ("ERNEST_RESEARCH_MODEL", "Research model", "Models", False, "anthropic:claude-opus-5"),
    ("ERNEST_EMBED_MODEL", "Embedding model", "Models", False, "openai:text-embedding-3-small"),
    ("ANTHROPIC_API_KEY", "Anthropic API key", "API keys", True, "sk-ant-…"),
    ("OPENAI_API_KEY", "OpenAI API key", "API keys", True, "sk-…"),
    ("ERNEST_DISCORD_TOKEN", "Discord bot token", "Discord", True, "bot token"),
    ("ERNEST_DISCORD_USER_ID", "Your Discord user ID", "Discord", False, "numeric id"),
    ("CANVAS_BASE_URL", "Canvas base URL", "Canvas", False, "https://school.instructure.com"),
    ("CANVAS_TOKEN", "Canvas access token", "Canvas", True, "canvas token (if available)"),
    ("CANVAS_ICS_URL", "Canvas calendar feed URL (no-token)", "Canvas", True,
     "https://…instructure.com/feeds/calendars/….ics"),
    ("ERNEST_ACCOUNTS", "Mail accounts (provider:name, comma-sep)", "Mail",
     False, "gmail:work,gmail:personal,outlook:business,outlook:school"),
    ("GOOGLE_CREDENTIALS_DIR", "Google credentials dir", "Mail", False, "./state/google"),
    ("MS_CLIENT_ID", "Microsoft/Outlook client ID", "Mail", False, "azure app (client) id"),
    ("MS_TENANT", "Microsoft tenant", "Mail", False, "common"),
    ("ERNEST_PRIORITY_SENDERS", "Always-ping senders (comma-sep: emails or domains)",
     "Priority alerts", False, "boss@company.com, @bigclient.com, agent@lit.com"),
    ("ERNEST_PRIORITY_KEYWORDS", "Always-ping keywords (comma-sep)", "Priority alerts",
     False, "contract, invoice, urgent, wedding"),
    ("ERNEST_DRAFT_REPLIES", "Draft replies to needs-reply email (1 on / 0 off)",
     "Drafting", False, "1"),
    ("ERNEST_DRAFT_MAX", "Max drafts per triage run", "Drafting", False, "5"),
    ("ERNEST_TRIAGE_LIMIT", "Emails scanned per account per run", "Mail", False, "50"),
    ("ERNEST_DIGEST_CATEGORIES", "Digest shows these in full (comma-sep); rest filed quietly",
     "Mail", False, "urgent,needs_reply,needs_action"),
    ("ERNEST_NEWS_FEEDS", "News RSS feeds (comma-sep)", "News", False, "https://…/rss"),
    ("ERNEST_RESEARCH_BUDGET_USD", "Research budget (USD/run)", "Research", False, "5"),
    ("ERNEST_LAT", "Latitude (weather)", "Weather", False, "30.27"),
    ("ERNEST_LON", "Longitude (weather)", "Weather", False, "-97.74"),
]

_LINE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")


def read_values(path: str) -> dict[str, str]:
    """Return {KEY: value} for assignment lines (ignores comments/blanks)."""
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            m = _LINE.match(line)
            if m:
                values[m.group(1)] = m.group(2).strip()
    return values


def is_set(path: str, key: str) -> bool:
    return bool(read_values(path).get(key))


def write_values(path: str, updates: dict[str, str]) -> None:
    """Apply ``updates`` (KEY -> value) to ``path``.

    Existing assignments are edited in place; unknown keys are appended. Comments,
    blank lines, and unrelated keys are preserved. An empty-string update is
    treated as "leave unchanged" so blank form fields never wipe a stored secret.
    """
    updates = {k: v for k, v in updates.items() if v != ""}
    if not updates:
        return

    lines: list[str] = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()

    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = _LINE.match(line)
        if m and m.group(1) in updates:
            key = m.group(1)
            out.append(f"{key}={updates[key]}\n")
            seen.add(key)
        else:
            out.append(line)

    remaining = [k for k in updates if k not in seen]
    if remaining:
        if out and not out[-1].endswith("\n"):
            out.append("\n")
        out.append("\n# Added by the dashboard\n")
        out.extend(f"{k}={updates[k]}\n" for k in remaining)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(out)
    try:
        os.chmod(path, 0o600)  # keep secrets owner-readable only
    except OSError:
        pass
