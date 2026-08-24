"""Spoken speech: the puck's ears and mouth.

Two thin wrappers over OpenAI's audio endpoints, riding the same client
``llm.py`` builds so the OpenAI key and config live in one place:

  transcribe(cfg, wav_path) -> str      speech  → text   (STT, Whisper)
  synthesize(cfg, text, out) -> Path    text    → speech (TTS)

This is deliberately provider-simple for V0 (the M2 laptop surface): one HTTP
round-trip each way, no local model, no heavy deps. The brain that decides what
to *say* is the existing intent router — this module only moves audio in and out.
Local/streaming STT (faster-whisper) and a wake word come later, on the puck.
"""

from __future__ import annotations

from pathlib import Path

from . import ConfigError
from .audit import log_event
from .config import Config
from .llm import _openai


def transcribe(cfg: Config, wav_path: str | Path) -> str:
    """Return the text of a spoken WAV clip, or "" if nothing was heard."""
    client = _openai(cfg)
    kwargs = {"language": cfg.stt_language} if cfg.stt_language else {}
    with open(wav_path, "rb") as fh:
        resp = client.audio.transcriptions.create(
            model=cfg.stt_model,
            file=fh,
            response_format="text",
            **kwargs,
        )
    # response_format="text" returns a bare string; guard for object shapes too.
    text = (resp if isinstance(resp, str) else getattr(resp, "text", "")).strip()
    log_event("speech", "transcribed", {"chars": len(text)})
    return text


def synthesize(cfg: Config, text: str, out_path: str | Path) -> Path:
    """Render ``text`` to speech (mp3) at ``out_path`` via the configured provider."""
    out = Path(out_path)
    provider = (cfg.tts_provider or "openai").lower()
    if provider == "elevenlabs":
        _synthesize_elevenlabs(cfg, text, out)
    else:
        _synthesize_openai(cfg, text, out)
    log_event("speech", "synthesized", {"chars": len(text), "provider": provider})
    return out


def _synthesize_openai(cfg: Config, text: str, out: Path) -> None:
    client = _openai(cfg)
    with client.audio.speech.with_streaming_response.create(
        model=cfg.tts_model,
        voice=cfg.tts_voice,
        input=text,
    ) as resp:
        resp.stream_to_file(out)


def _synthesize_elevenlabs(cfg: Config, text: str, out: Path) -> None:
    if not cfg.eleven_api_key:
        raise ConfigError("ELEVENLABS_API_KEY is required for tts_provider=elevenlabs")
    import requests

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{cfg.eleven_voice_id}"
    resp = requests.post(
        url,
        headers={"xi-api-key": cfg.eleven_api_key, "accept": "audio/mpeg"},
        json={
            "text": text,
            "model_id": cfg.eleven_model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        },
        timeout=60,
    )
    resp.raise_for_status()
    out.write_bytes(resp.content)
