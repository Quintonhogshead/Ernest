"""Interactive Discord bot — Ernest that listens.

A gateway (websocket) client that runs alongside the scheduler and dashboard in
the always-on process. It answers DMs from the owner only, and is read-only:

  ask <question>      → answer from your library, with citations
  research <topic>    → frontier-model briefing (slow), saved + ingested
  status              → what's configured and how the library/triage look
  help                → this list
  <anything else>     → treated as an `ask`

It never sends mail, books events, or acts on your accounts — that's later,
gated work. discord.py is imported lazily so the rest of Ernest runs without it.
"""

from __future__ import annotations

import asyncio
import threading

from .audit import log_event
from .config import Config, load

HELP = (
    "🎩 **Ernest** — I can:\n"
    "• `ask <question>` — answer from your library (email, Canvas, notes, past research)\n"
    "• `research <topic>` — a full cited briefing (takes a few minutes)\n"
    "• `status` — what I can see right now\n"
    "• `help` — this message\n"
    "_Anything else, I'll treat as an ask. I'm read-only — I won't send or change anything._"
)

_MAX = 1900


def route(content: str) -> tuple[str, str]:
    """Pure command parser → (command, argument). Testable without Discord."""
    text = (content or "").strip()
    low = text.lower()
    if low in ("help", "?", "commands", "/help"):
        return "help", ""
    if low in ("status", "stat", "/status"):
        return "status", ""
    for prefix in ("ask:", "ask ", "? "):
        if low.startswith(prefix):
            return "ask", text[len(prefix):].strip()
    if low.startswith("research"):
        return "research", text[len("research"):].lstrip(": ").strip()
    if not text:
        return "help", ""
    return "ask", text  # free-form → ask


# ── blocking work, run off the event loop via asyncio.to_thread ──────────────

def _ask_sync(cfg: Config, question: str) -> str:
    from jobs.ask import answer

    reply, hits = answer(cfg, question)
    if hits:
        sources = "\n".join(
            f"[{i}] {h['source']} — {h['title'] or 'untitled'}"
            for i, h in enumerate(hits, 1)
        )
        return f"{reply}\n\n__Sources__\n{sources}"
    return reply


def _research_sync(cfg: Config, topic: str) -> str:
    from ernest import library, research
    from ernest.store import connect

    result = research.run(cfg, topic)
    conn = connect()
    library.add_document(conn, cfg, f"research:{topic}", f"Briefing: {topic}", result["briefing"])
    return f"🔬 **Research: {topic}**\n\n{result['summary']}\n\n_Full briefing saved to {result['path']} and added to your library._"


def _status_sync(cfg: Config) -> str:
    from ernest import mail
    from ernest.audit import read_events
    from ernest.store import connect

    conn = connect()
    try:
        lib = conn.execute("SELECT COUNT(*) n FROM library").fetchone()["n"]
    except Exception:
        lib = "?"
    accounts = ", ".join(f"{p}:{n}" for p, n in mail.accounts(cfg)) or "none configured"
    last = [e for e in read_events() if e.get("job") == "triage" and e.get("action") == "digest_sent"]
    last_triage = last[-1]["ts"][:19].replace("T", " ") + " UTC" if last else "not yet"
    return (
        f"🎩 **Status**\n"
        f"• Accounts: {accounts}\n"
        f"• Library: {lib} chunks\n"
        f"• Last triage digest: {last_triage}\n"
        f"• Models — triage `{cfg.triage_model}`, ask `{cfg.ask_model}`"
    )


async def _send(channel, text: str) -> None:
    for i in range(0, len(text), _MAX):
        await channel.send(text[i : i + _MAX])


def run() -> None:
    cfg = load()
    if not cfg.discord_token or not cfg.discord_user_id:
        log_event("bot", "not_configured", {})
        print("[bot] Discord token/user id missing — interactive bot not started.")
        return
    owner_id = int(cfg.discord_user_id)

    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        log_event("bot", "ready", {"user": str(client.user)})
        print(f"[bot] connected as {client.user}")

    @client.event
    async def on_message(message):
        if message.author.id == client.user.id:
            return
        if message.author.id != owner_id:  # owner only
            return
        if message.guild is not None:  # DMs only
            return
        cfg = load()  # reload each command so dashboard config changes take effect live
        command, arg = route(message.content)
        log_event("bot", "command", {"command": command})
        try:
            async with message.channel.typing():
                if command == "help":
                    await _send(message.channel, HELP)
                elif command == "status":
                    await _send(message.channel, await asyncio.to_thread(_status_sync, cfg))
                elif command == "research":
                    if not arg:
                        await _send(message.channel, "Give me a topic: `research <topic>`")
                    else:
                        await message.channel.send(f"🔬 Researching *{arg}*… (a few minutes)")
                        await _send(message.channel, await asyncio.to_thread(_research_sync, cfg, arg))
                else:  # ask
                    await _send(message.channel, await asyncio.to_thread(_ask_sync, cfg, arg))
        except Exception as exc:
            log_event("bot", "handler_error", {"error": str(exc)})
            await message.channel.send(f"⚠️ Something went wrong: {exc}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(client.start(cfg.discord_token))
    except Exception as exc:
        log_event("bot", "crashed", {"error": str(exc)})
        print(f"[bot] stopped: {exc}")


def start_background() -> threading.Thread:
    thread = threading.Thread(target=run, daemon=True, name="ernest-bot")
    thread.start()
    return thread
