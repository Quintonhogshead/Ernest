# Deploying the Ernest dashboard to Fly.io

The dashboard can run in two places:

- **Locally** (default, no password): `python -m dashboard.app` → http://127.0.0.1:8787
- **On Fly.io** (this guide): a private, password-protected, HTTPS URL you can
  reach from anywhere to manage keys and check status.

> ⚠️ **Read this first.** This app stores your API keys and can launch jobs. On
> any non-localhost host it **requires** a password and refuses to start without
> one. Even so, anyone with the URL **and** the password can read and rewrite your
> keys. Use a long random password, keep the app private, and never share the
> URL. If that tradeoff isn't worth it, run it locally instead — the local mode
> is exactly as capable for entering keys.

## What you get

A single small machine that serves the dashboard over HTTPS. Your `.env` and the
library database live on a **persistent volume** (`/data`), not baked into the
image, so redeploys don't wipe them. The machine scales to zero when idle.

## Prerequisites

- A Fly.io account and [`flyctl`](https://fly.io/docs/hann/install-flyctl/) installed:
  ```bash
  curl -L https://fly.io/install.sh | sh
  fly auth login
  ```

## One-time setup

From the repo root:

```bash
# 1. Pick a unique app name (edit `app = ...` in fly.toml, or let launch rename it).
fly launch --no-deploy --copy-config --name ernest-dash-<your-suffix>

# 2. Create the persistent volume the config mounts at /data (same name as fly.toml).
fly volumes create ernest_data --size 1 --region iad

# 3. Generate a strong password and save it in your password manager:
python -c 'import secrets; print(secrets.token_urlsafe(24))'
#    Then set it as a Fly secret (this is the ONLY thing between the internet and
#    your keys):
fly secrets set ERNEST_DASHBOARD_PASSWORD="paste-the-generated-value-here"

# 4. Deploy.
fly deploy

# 5. Open it (log in with any username and the password above).
fly open
```

## Using it

- Browser will prompt for HTTP Basic Auth: **any username**, password =
  `ERNEST_DASHBOARD_PASSWORD`.
- Enter your API keys and config; click **Save**. They're written to
  `/data/.env` on the volume.
- The "Try a job" buttons run read-only dry-runs on the machine.

## Keeping keys as Fly secrets instead (optional, more secure)

The dashboard writes keys to the volume so the UI can edit them. If you'd rather
the keys live as Fly **secrets** (encrypted, injected as env vars, not editable
from the UI), set them directly and treat the dashboard as read-only status:

```bash
fly secrets set ANTHROPIC_API_KEY=... OPENAI_API_KEY=... ERNEST_DISCORD_TOKEN=...
```

Env vars always shadow the `.env` file, so anything set this way wins and the
dashboard will simply show it as "set".

## Running Ernest's jobs on Fly (later)

This deploy runs the **dashboard**. To also run the scheduled jobs (triage,
briefs) on the same machine, add a process group or a Fly
[scheduled machine](https://fly.io/docs/hann/scheduled-machines/) that runs
`python -m jobs.<name>` — they'll share `/data`. Note the iMessage reader only
works on your Mac (it reads the local Messages database), so keep
`jobs.messages_sync` on the laptop.

## Costs

A `shared-cpu-1x` / 256 MB machine that scales to zero plus a 1 GB volume runs a
few dollars a month or less. See Fly's pricing.

## Tearing down

```bash
fly apps destroy ernest-dash-<your-suffix>
```
