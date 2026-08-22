# 🎩 Ernest

A personal chief-of-staff agent. Ernest watches your inboxes, Canvas, and news;
triages what arrives; briefs you morning and evening over Discord; remembers
everything it reads in a searchable **library**; and runs **frontier-model
research** on demand. This repository is the **read-only core** — Ernest reads,
classifies, summarizes, and messages *you*. It never sends, drafts, books, or
deletes on your accounts. Those capabilities are earned later, one at a time,
through the trust ladder described in [PLAN.md](PLAN.md).

> Design docs: **[PLAN.md](PLAN.md)** (the full vision, trust ladder, away mode,
> roadmap) and **[RUNBOOK.md](RUNBOOK.md)** (milestone-by-milestone build spec).

## What's built

| Job | Command | What it does |
|---|---|---|
| Liveness | `python -m jobs.ping` | DM yourself that Ernest is online |
| Email triage | `python -m jobs.triage --dry-run` | Classify unread mail across accounts → digest |
| Canvas | `python -m jobs.canvas_sync --dry-run` | Upcoming work + announcements → digest |
| News desk | `python -m jobs.news --dry-run` | RSS scored against your interests → digest |
| Briefs | `python -m jobs.brief morning\|evening` | Daily brief / evening wrap |
| Ingest | `python -m jobs.ingest notes.md` | Add files to the library |
| Ask | `python -m jobs.ask "..."` | Answer from the library, with citations |
| Research | `python -m jobs.research "..."` | Frontier-model briefing, saved + ingested |
| Texts (macOS) | `python -m jobs.messages_sync --dry-run` | iMessage/SMS → triage digest |

Every job is read-only and respects `ERNEST_PAUSED`. All outbound writing is
limited to Discord DMs to you.

## Models are configuration

No model ID is hard-coded. Each job's model is a `provider:model` spec in `.env`,
resolved by [`ernest/llm.py`](ernest/llm.py) — the only module that imports the
Anthropic/OpenAI SDKs. Mix providers freely:

```
ERNEST_TRIAGE_MODEL=anthropic:claude-haiku-4-5
ERNEST_ASK_MODEL=anthropic:claude-sonnet-5
ERNEST_RESEARCH_MODEL=anthropic:claude-opus-5
ERNEST_EMBED_MODEL=openai:text-embedding-3-small   # embeddings require openai:
```

Swap any of them for an `openai:` model (e.g. `openai:gpt-5.1-mini`) without
touching code.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill it in (see below)
pytest                        # sanity check (no keys/network needed)
python -m jobs.ping           # first DM from Ernest
```

### Filling in `.env`

1. **Discord bot** — Developer Portal → New Application "Ernest" → Bot → copy the
   token into `ERNEST_DISCORD_TOKEN`. Invite the bot to a private server you're in
   (it can only DM users it shares a server with). Enable Developer Mode in
   Discord, copy your own user ID into `ERNEST_DISCORD_USER_ID`.
2. **Canvas** (optional) — Account → Settings → *New Access Token* →
   `CANVAS_TOKEN`; set `CANVAS_BASE_URL` to `https://<your-school>.instructure.com`.
   Skip this and the `canvas_sync` job simply won't run.
3. **Mail accounts** — `ERNEST_ACCOUNTS` is a comma-separated list of
   `provider:name` entries; providers are `gmail` and `outlook`. Example for two
   of each:
   ```
   ERNEST_ACCOUNTS=gmail:work,gmail:personal,outlook:business,outlook:school
   ```
   - **Gmail** — create one Desktop-app OAuth client (Gmail API enabled), save it
     as `state/google/credentials.json`, then authorize each Gmail account
     read-only:
     ```bash
     python scripts/authorize.py gmail work
     python scripts/authorize.py gmail personal
     ```
   - **Outlook / Microsoft 365** — register a **public client** app in the
     [Azure/Entra portal](https://entra.microsoft.com) (App registrations → New):
     set "Allow public client flows" = Yes, add the delegated **`Mail.Read`**
     permission, and copy the **Application (client) ID** into `MS_CLIENT_ID`
     (leave `MS_TENANT=common` for personal/multi-tenant). Then authorize each
     Outlook account with the device-code flow:
     ```bash
     python scripts/authorize.py outlook business   # prints a URL + code to enter
     python scripts/authorize.py outlook school
     ```
   All four token files land in `state/google/` (`token_*.json` for Gmail,
   `ms_token_*.json` for Outlook) and are git-ignored.
4. **Models** — `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY`.
5. **News** — comma-separated RSS URLs in `ERNEST_NEWS_FEEDS`; edit
   `state/memory/interests.md` to steer scoring.

### Dashboard

A local control panel for entering keys and checking status — no config file
editing by hand:

```bash
python -m dashboard.app        # http://127.0.0.1:8787 (localhost, no password)
```

It edits `.env`, shows which keys are set (never displaying secret values), and
has buttons to run read-only dry-runs. To reach it from anywhere, deploy it to
Fly.io behind a password over HTTPS — see [DEPLOY-FLY.md](DEPLOY-FLY.md). It
**fails closed**: on any non-localhost host it refuses to start without
`ERNEST_DASHBOARD_PASSWORD`.

### Scheduling

See [ops/README.md](ops/README.md) for the launchd templates (triage every 15
min, briefs at 7:30 and 21:00, etc.).

## Architecture in one breath

```
scheduler (launchd) → jobs/*.py → ernest/* (read integrations, model layer,
   library) → SQLite state + library → Discord DM to you
```

The classifier that reads untrusted email has **no tools** and returns only JSON;
a plain-code policy layer decides what happens; nothing in this repo can act on an
account. That separation is what makes the roadmap's later autonomy safe. See
[PLAN.md](PLAN.md).

## Safety posture

- **Read-only everywhere** except Discord DMs to you and embedding API calls.
- **Secrets** live in `.env` / the `state/google/` tokens, all git-ignored.
- **Injection defense**: retrieved and received content is data, never
  instructions — prompts say so, and the reader has nothing to execute.
- **Kill switch**: `ERNEST_PAUSED=1`.
- **No self-botting**: Discord access is a bot token only; personal DMs and user
  accounts are never automated (Discord ToS).

## Tests

```bash
pytest
```

Tests run without any API keys, network, or the heavy SDKs installed (the SDKs
are imported lazily). They cover config, JSON parsing/validation, vector math,
chunking, library ingest + hybrid search, HTML stripping, and the iMessage blob
decoder.
