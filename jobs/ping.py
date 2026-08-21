"""Liveness check: DM the owner that Ernest is online. Respects the pause switch."""

from __future__ import annotations

from datetime import datetime, timezone

from ernest import chan
from ernest.audit import log_event
from ernest.config import load
from ernest.guard import halt_if_paused


def main() -> None:
    cfg = load()
    halt_if_paused(cfg, "ping")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ok = chan.send(cfg, f"🎩 Ernest online — {stamp}")
    log_event("ping", "sent", {"ok": ok})
    print("sent" if ok else "send failed (see audit log)")


if __name__ == "__main__":
    main()
