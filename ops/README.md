# Scheduling Ernest (macOS launchd)

The jobs are plain `python -m jobs.<name>` entrypoints. On macOS, run them on a
schedule with launchd. Templates live in this directory as `*.plist.template`.

## One-time setup

1. Fill in the two placeholders in each template:
   - `__ERNEST_DIR__` → the absolute path to this repo (e.g. `/Users/you/Desktop/Ernest`)
   - `__PYTHON__` → the absolute path to your venv Python (`which python` after `source .venv/bin/activate`)
2. Copy each `*.plist.template` to `~/Library/LaunchAgents/<label>.plist` (drop the `.template`).
3. Load them:

   ```bash
   for p in ~/Library/LaunchAgents/com.ernest.*.plist; do launchctl load "$p"; done
   ```

Validate any plist before loading with `plutil -lint <file>`.

## Schedule

| Label | Job | Cadence |
|---|---|---|
| `com.ernest.triage`   | `jobs.triage`        | every 15 min, 7:00–22:00 |
| `com.ernest.canvas`   | `jobs.canvas_sync`   | 08:00 and 16:00 |
| `com.ernest.news`     | `jobs.news`          | daily 08:05 |
| `com.ernest.brief-am` | `jobs.brief morning` | daily 07:30 |
| `com.ernest.brief-pm` | `jobs.brief evening` | daily 21:00 |

`jobs.messages_sync` (iMessage) and `jobs.research` are run on demand, not on a
schedule, until you decide otherwise.

## Pausing

`launchctl unload` a plist to stop that job, or set `ERNEST_PAUSED=1` in `.env`
to halt every writing job at once (readers keep logging).

> A sleeping laptop won't run these. For 24/7, move to an always-on Mac or a
> small VPS (see PLAN.md, "Four ways to run it").
