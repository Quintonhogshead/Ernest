"""Configuration loader.

Every tunable is an environment variable (see .env.example). Models are
configuration, never hard-coded: each is a ``provider:model`` spec resolved by
``ernest.llm``. Loading is side-effect free apart from reading ``.env``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

from . import ConfigError

try:  # dotenv is convenient but not required (e.g. under launchd with a real env)
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - trivial import guard
    def load_dotenv(*_a, **_k):  # type: ignore
        return False


@dataclass(frozen=True)
class Config:
    # models
    triage_model: str = "anthropic:claude-haiku-4-5"
    ask_model: str = "anthropic:claude-sonnet-5"
    research_model: str = "anthropic:claude-opus-5"
    embed_model: str = "openai:text-embedding-3-small"
    # keys
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # discord
    discord_token: str | None = None
    discord_user_id: str | None = None
    # canvas (API needs a token; ICS feed is the no-token fallback)
    canvas_base_url: str | None = None
    canvas_token: str | None = None
    canvas_ics_url: str | None = None
    # mail
    google_credentials_dir: str = "./state/google"
    accounts: tuple[str, ...] = ()
    ms_client_id: str | None = None
    ms_tenant: str = "common"
    # news
    news_feeds: tuple[str, ...] = ()
    # library / research
    ingest: bool = True
    research_budget_usd: float = 5.0
    # weather
    lat: str | None = None
    lon: str | None = None
    # kill switch
    paused: bool = False


def _split(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(p.strip() for p in value.split(",") if p.strip())


def load() -> Config:
    # Honor ERNEST_ENV_PATH so jobs read the same .env the dashboard writes
    # (e.g. a mounted volume at /data/.env on Fly.io). Falls back to the default
    # search (a .env in the working directory) for local runs.
    env_path = os.environ.get("ERNEST_ENV_PATH")
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()
    g = os.environ.get
    return Config(
        triage_model=g("ERNEST_TRIAGE_MODEL") or "anthropic:claude-haiku-4-5",
        ask_model=g("ERNEST_ASK_MODEL") or "anthropic:claude-sonnet-5",
        research_model=g("ERNEST_RESEARCH_MODEL") or "anthropic:claude-opus-5",
        embed_model=g("ERNEST_EMBED_MODEL") or "openai:text-embedding-3-small",
        anthropic_api_key=g("ANTHROPIC_API_KEY") or None,
        openai_api_key=g("OPENAI_API_KEY") or None,
        discord_token=g("ERNEST_DISCORD_TOKEN") or None,
        discord_user_id=g("ERNEST_DISCORD_USER_ID") or None,
        canvas_base_url=(g("CANVAS_BASE_URL") or "").rstrip("/") or None,
        canvas_token=g("CANVAS_TOKEN") or None,
        canvas_ics_url=g("CANVAS_ICS_URL") or None,
        google_credentials_dir=g("GOOGLE_CREDENTIALS_DIR") or "./state/google",
        accounts=_split(g("ERNEST_ACCOUNTS")),
        ms_client_id=g("MS_CLIENT_ID") or None,
        ms_tenant=g("MS_TENANT") or "common",
        news_feeds=_split(g("ERNEST_NEWS_FEEDS")),
        ingest=(g("ERNEST_INGEST") or "1") != "0",
        research_budget_usd=float(g("ERNEST_RESEARCH_BUDGET_USD") or "5"),
        lat=g("ERNEST_LAT") or None,
        lon=g("ERNEST_LON") or None,
        paused=bool(g("ERNEST_PAUSED")),
    )


def require(cfg: Config, *names: str) -> None:
    """Raise ConfigError listing any of ``names`` that are unset/empty on cfg."""
    valid = {f.name for f in fields(Config)}
    missing = []
    for name in names:
        if name not in valid:
            raise ConfigError(f"unknown config field: {name}")
        if not getattr(cfg, name):
            missing.append(name)
    if missing:
        raise ConfigError("missing required config: " + ", ".join(missing))
