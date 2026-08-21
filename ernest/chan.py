"""Your channel: the Discord bot (send-only).

Named ``chan`` to avoid colliding with the ``discord.py`` package a later,
interactive version will use. This module only DMs the owner via Ernest's bot
over the REST API — no gateway connection, no listening. Interactive approvals
(buttons, free-form requests) are senior-model work for a later phase.

Prerequisite: the bot must share a private server with you — Discord only lets a
bot open a DM with a user it shares a guild with.
"""

from __future__ import annotations

import os
import time

import requests

from . import ConfigError
from .audit import log_event
from .config import Config

API = "https://discord.com/api/v10"
_DM_CACHE = os.path.join("state", "discord_dm_channel.txt")
_LIMIT = 1900  # Discord hard limit is 2000; leave headroom


def _headers(cfg: Config) -> dict:
    return {
        "Authorization": f"Bot {cfg.discord_token}",
        "User-Agent": "ErnestBot (private, 0.1)",
        "Content-Type": "application/json",
    }


def _dm_channel_id(cfg: Config) -> str:
    if os.path.exists(_DM_CACHE):
        cached = open(_DM_CACHE, encoding="utf-8").read().strip()
        if cached:
            return cached
    resp = requests.post(
        f"{API}/users/@me/channels",
        headers=_headers(cfg),
        json={"recipient_id": str(cfg.discord_user_id)},
        timeout=15,
    )
    resp.raise_for_status()
    channel_id = str(resp.json()["id"])
    os.makedirs(os.path.dirname(_DM_CACHE), exist_ok=True)
    with open(_DM_CACHE, "w", encoding="utf-8") as fh:
        fh.write(channel_id)
    return channel_id


def _split(text: str) -> list[str]:
    parts: list[str] = []
    for block in text.split("\n\n"):
        while len(block) > _LIMIT:
            cut = block.rfind("\n", 0, _LIMIT)
            cut = cut if cut > 0 else _LIMIT
            parts.append(block[:cut])
            block = block[cut:].lstrip("\n")
        if block:
            parts.append(block)
    # coalesce tiny parts back together under the limit
    out: list[str] = []
    for p in parts:
        if out and len(out[-1]) + len(p) + 2 <= _LIMIT:
            out[-1] = out[-1] + "\n\n" + p
        else:
            out.append(p)
    return out or [""]


def send(cfg: Config, text: str) -> bool:
    """DM the owner. Returns True on success; best-effort with one retry."""
    if not cfg.discord_token or not cfg.discord_user_id:
        raise ConfigError("ERNEST_DISCORD_TOKEN and ERNEST_DISCORD_USER_ID required")
    try:
        channel_id = _dm_channel_id(cfg)
    except Exception as exc:
        log_event("chan", "dm_channel_failed", {"error": str(exc)})
        return False

    ok = True
    for part in _split(text):
        url = f"{API}/channels/{channel_id}/messages"
        for attempt in (1, 2):
            try:
                resp = requests.post(
                    url, headers=_headers(cfg), json={"content": part}, timeout=15
                )
                if resp.status_code == 429:  # rate limited
                    retry_after = float(resp.json().get("retry_after", 2))
                    time.sleep(min(retry_after, 10))
                    continue
                resp.raise_for_status()
                break
            except Exception as exc:
                if attempt == 2:
                    log_event("chan", "send_failed", {"error": str(exc)})
                    ok = False
                else:
                    time.sleep(2)
    return ok
