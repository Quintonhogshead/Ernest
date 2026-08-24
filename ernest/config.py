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

# Quinton's standing default for every generative model ("Luna"). Still just a
# default: any ERNEST_*_MODEL env var overrides it. Embeddings are excluded —
# Luna is a chat model and can't embed.
_LUNA = "openai:gpt-5.6-luna"


@dataclass(frozen=True)
class Config:
    # models — default to Luna; override any of them with ERNEST_*_MODEL
    triage_model: str = _LUNA
    ask_model: str = _LUNA
    research_model: str = _LUNA
    embed_model: str = "openai:text-embedding-3-small"
    # keys
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # local models via Ollama's OpenAI-compatible endpoint (ollama: specs)
    ollama_base_url: str = "http://localhost:11434/v1"
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
    # calendar concierge: which Google account hosts the canonical "Ernest" calendar
    # (else the first gmail: account with a gcal token); how far ahead to mirror.
    calendar_account: str | None = None
    gcal_sync_days: int = 60
    # meeting memory: how far back to scan for new Meet transcripts, and how many
    # minutes before a meeting to send the recap.
    meet_sync_days: int = 7
    meet_reminder_lead_min: int = 10
    # news
    news_feeds: tuple[str, ...] = ()
    # priority alerts — always ping on these, regardless of the model's judgment
    priority_senders: tuple[str, ...] = ()
    priority_keywords: tuple[str, ...] = ()
    # reply drafting (step 1: draft-to-Discord, never auto-sends)
    draft_replies: bool = True
    draft_max: int = 5
    triage_limit: int = 50
    # which categories appear in full in the digest; the rest are filed quietly
    digest_categories: tuple[str, ...] = ("urgent", "needs_reply", "needs_action")
    # library / research
    ingest: bool = True
    research_budget_usd: float = 5.0
    database_url: str | None = None  # set → use Postgres+pgvector; unset → SQLite
    # reranking (Phase 3): retrieve a wide pool, then an LLM reorders to top-k.
    # Off by default — prove it helps with `python -m jobs.eval` before enabling.
    rerank: bool = False
    rerank_model: str | None = None  # falls back to triage_model when unset
    rerank_candidates: int = 30  # pool size fed to the reranker
    # weather
    lat: str | None = None
    lon: str | None = None
    # voice: LLM composes user-facing messages as plain English (else raw templates)
    voice: bool = True
    voice_model: str | None = None  # falls back to triage_model when unset
    # spoken speech (the voice puck)
    tts_provider: str = "openai"  # "openai" or "elevenlabs"
    stt_model: str = "whisper-1"
    stt_language: str = "en"  # pin STT language (ISO-639-1); "" = auto-detect
    # OpenAI TTS
    tts_model: str = "gpt-4o-mini-tts"
    tts_voice: str = "onyx"  # any OpenAI voice name
    # ElevenLabs TTS (better voices; used when tts_provider="elevenlabs")
    eleven_api_key: str | None = None
    eleven_voice_id: str = "pNInz6obpgDQGcFmaJgB"  # "Adam" (prebuilt); override to taste
    eleven_model: str = "eleven_turbo_v2_5"  # low-latency; eleven_multilingual_v2 = richer
    # Wake word (hands-free loop): a local openWakeWord model, no cloud until triggered.
    # "hey_jarvis" is a bundled model that fits the persona; a custom "Hey Ernest"
    # model can be trained and dropped in later (set to its .onnx path).
    wake_model: str = "hey_jarvis"
    wake_threshold: float = 0.5  # detection confidence 0–1; raise if it false-triggers
    wake_ack_sound: str = "/System/Library/Sounds/Pop.aiff"  # instant chime on wake
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
        triage_model=g("ERNEST_TRIAGE_MODEL") or _LUNA,
        ask_model=g("ERNEST_ASK_MODEL") or _LUNA,
        research_model=g("ERNEST_RESEARCH_MODEL") or _LUNA,
        embed_model=g("ERNEST_EMBED_MODEL") or "openai:text-embedding-3-small",
        anthropic_api_key=g("ANTHROPIC_API_KEY") or None,
        openai_api_key=g("OPENAI_API_KEY") or None,
        ollama_base_url=g("ERNEST_OLLAMA_BASE_URL") or "http://localhost:11434/v1",
        discord_token=g("ERNEST_DISCORD_TOKEN") or None,
        discord_user_id=g("ERNEST_DISCORD_USER_ID") or None,
        canvas_base_url=(g("CANVAS_BASE_URL") or "").rstrip("/") or None,
        canvas_token=g("CANVAS_TOKEN") or None,
        canvas_ics_url=g("CANVAS_ICS_URL") or None,
        google_credentials_dir=g("GOOGLE_CREDENTIALS_DIR") or "./state/google",
        accounts=_split(g("ERNEST_ACCOUNTS")),
        ms_client_id=g("MS_CLIENT_ID") or None,
        ms_tenant=g("MS_TENANT") or "common",
        calendar_account=g("ERNEST_CALENDAR_ACCOUNT") or None,
        gcal_sync_days=int(g("ERNEST_GCAL_SYNC_DAYS") or "60"),
        meet_sync_days=int(g("ERNEST_MEET_SYNC_DAYS") or "7"),
        meet_reminder_lead_min=int(g("ERNEST_MEET_REMINDER_LEAD_MIN") or "10"),
        news_feeds=_split(g("ERNEST_NEWS_FEEDS")),
        priority_senders=_split(g("ERNEST_PRIORITY_SENDERS")),
        priority_keywords=_split(g("ERNEST_PRIORITY_KEYWORDS")),
        draft_replies=(g("ERNEST_DRAFT_REPLIES") or "1") != "0",
        draft_max=int(g("ERNEST_DRAFT_MAX") or "5"),
        triage_limit=int(g("ERNEST_TRIAGE_LIMIT") or "50"),
        digest_categories=_split(g("ERNEST_DIGEST_CATEGORIES"))
        or ("urgent", "needs_reply", "needs_action"),
        ingest=(g("ERNEST_INGEST") or "1") != "0",
        research_budget_usd=float(g("ERNEST_RESEARCH_BUDGET_USD") or "5"),
        database_url=g("DATABASE_URL") or None,
        rerank=(g("ERNEST_RERANK") or "0") != "0",
        rerank_model=g("ERNEST_RERANK_MODEL") or None,
        rerank_candidates=int(g("ERNEST_RERANK_CANDIDATES") or "30"),
        lat=g("ERNEST_LAT") or None,
        lon=g("ERNEST_LON") or None,
        voice=(g("ERNEST_VOICE") or "1") != "0",
        voice_model=g("ERNEST_VOICE_MODEL") or None,
        stt_model=g("ERNEST_STT_MODEL") or "whisper-1",
        stt_language=g("ERNEST_STT_LANGUAGE") if g("ERNEST_STT_LANGUAGE") is not None else "en",
        # Default to ElevenLabs the moment a key is present — that's the intent.
        tts_provider=g("ERNEST_TTS_PROVIDER")
        or ("elevenlabs" if g("ELEVENLABS_API_KEY") else "openai"),
        tts_model=g("ERNEST_TTS_MODEL") or "gpt-4o-mini-tts",
        tts_voice=g("ERNEST_TTS_VOICE") or "onyx",
        eleven_api_key=g("ELEVENLABS_API_KEY") or None,
        eleven_voice_id=g("ERNEST_ELEVEN_VOICE_ID") or "pNInz6obpgDQGcFmaJgB",
        eleven_model=g("ERNEST_ELEVEN_MODEL") or "eleven_turbo_v2_5",
        wake_model=g("ERNEST_WAKE_MODEL") or "hey_jarvis",
        wake_threshold=float(g("ERNEST_WAKE_THRESHOLD") or "0.5"),
        wake_ack_sound=g("ERNEST_WAKE_ACK_SOUND") or "/System/Library/Sounds/Pop.aiff",
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
