"""In-process job scheduler for running Ernest on a server (e.g. the Fly machine).

Ticks once a minute and runs each due job as a subprocess (`python -m jobs.<x>`)
so a failing job can't take the scheduler down. Interval jobs (triage) run every
N seconds; daily jobs run at a local wall-clock time once per day. Local time is
resolved from ERNEST_TZ (default America/Chicago).

Start it from the dashboard process (ERNEST_RUN_SCHEDULER=1) so one always-on
machine serves the UI and runs the jobs, sharing the /data volume.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from datetime import date, datetime

from .audit import log_event

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# (key, argv-after-python, interval_seconds)
INTERVAL_JOBS = [
    ("triage", ["-m", "jobs.triage"], 15 * 60),
    ("gcal-sync", ["-m", "jobs.gcal_sync"], 30 * 60),
]
# (key, argv-after-python, (hour, minute))
DAILY_JOBS = [
    ("brief-morning", ["-m", "jobs.brief", "morning"], (7, 30)),
    ("canvas-am", ["-m", "jobs.canvas_sync"], (8, 0)),
    ("news", ["-m", "jobs.news"], (8, 5)),
    ("canvas-pm", ["-m", "jobs.canvas_sync"], (16, 0)),
    ("brief-evening", ["-m", "jobs.brief", "evening"], (21, 0)),
]


def _tz():
    name = os.environ.get("ERNEST_TZ") or "America/Chicago"
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            return None
    return None


def due_jobs(now: datetime, last_interval: dict[str, float],
             last_daily: dict[str, date]) -> list[tuple[str, list[str]]]:
    """Return [(key, argv), …] due at ``now``. Mutates the two state dicts.

    Pure enough to unit-test: pass a datetime and the state dicts.
    """
    out: list[tuple[str, list[str]]] = []
    epoch = now.timestamp()
    for key, argv, interval in INTERVAL_JOBS:
        if epoch - last_interval.get(key, 0.0) >= interval:
            last_interval[key] = epoch
            out.append((key, argv))
    for key, argv, (hh, mm) in DAILY_JOBS:
        if now.hour == hh and now.minute == mm and last_daily.get(key) != now.date():
            last_daily[key] = now.date()
            out.append((key, argv))
    return out


def _run(key: str, argv: list[str], root: str) -> None:
    try:
        proc = subprocess.run(
            [sys.executable, *argv], cwd=root, capture_output=True, text=True, timeout=600
        )
        log_event("scheduler", "ran",
                  {"job": key, "code": proc.returncode,
                   "tail": (proc.stdout or proc.stderr or "")[-200:]})
    except Exception as exc:
        log_event("scheduler", "run_failed", {"job": key, "error": str(exc)})


def run_forever(root: str | None = None) -> None:
    root = root or os.getcwd()
    tz = _tz()
    last_interval: dict[str, float] = {}
    last_daily: dict[str, date] = {}
    log_event("scheduler", "started", {"tz": os.environ.get("ERNEST_TZ") or "America/Chicago"})
    # Seed interval jobs so triage doesn't fire the instant we boot.
    now0 = datetime.now(tz) if tz else datetime.now()
    for key, _argv, _interval in INTERVAL_JOBS:
        last_interval[key] = now0.timestamp()
    while True:
        now = datetime.now(tz) if tz else datetime.now()
        for key, argv in due_jobs(now, last_interval, last_daily):
            _run(key, argv, root)
        time.sleep(60)


def start_background(root: str | None = None) -> threading.Thread:
    thread = threading.Thread(target=run_forever, args=(root,), daemon=True, name="ernest-scheduler")
    thread.start()
    return thread
