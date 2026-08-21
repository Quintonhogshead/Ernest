"""The kill switch. Every job calls halt_if_paused() before doing anything."""

from __future__ import annotations

import sys

from .audit import log_event
from .config import Config


def halt_if_paused(cfg: Config, job: str) -> None:
    """If ERNEST_PAUSED is set, log and exit cleanly. Readers still log elsewhere."""
    if cfg.paused:
        log_event(job, "paused_skip", {})
        print(f"[{job}] ERNEST_PAUSED is set — skipping.")
        sys.exit(0)
