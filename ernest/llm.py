"""The model layer — the only module that imports the Anthropic/OpenAI SDKs.

Every model call is selected by a ``provider:model`` spec (e.g.
``anthropic:claude-haiku-4-5`` or ``openai:gpt-5.1-mini``) so providers can be
mixed per job and swapped without code changes. SDKs are imported lazily so the
rest of Ernest (config, store, library, tests) runs without them installed.
"""

from __future__ import annotations

import json
import re

from . import ConfigError, ErnestError
from .config import Config


class LLMOutputError(ErnestError):
    """The model did not return usable output after a retry."""


_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def parse_spec(spec: str) -> tuple[str, str]:
    if ":" not in spec:
        raise ConfigError(f"model spec must be 'provider:model', got {spec!r}")
    provider, model = spec.split(":", 1)
    provider, model = provider.strip().lower(), model.strip()
    if provider not in ("anthropic", "openai"):
        raise ConfigError(f"unknown model provider {provider!r} in {spec!r}")
    if not model:
        raise ConfigError(f"empty model id in {spec!r}")
    return provider, model


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = _FENCE.sub("", text)
    return text.strip()


def _extract_json(text: str) -> dict:
    """Parse a JSON object from model text, tolerating fences and stray prose."""
    cleaned = _strip_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise LLMOutputError("no JSON object found in model output")


# ── provider clients (lazy) ──────────────────────────────────────────────────

def _anthropic(cfg: Config):
    if not cfg.anthropic_api_key:
        raise ConfigError("ANTHROPIC_API_KEY is required for an anthropic: model")
    import anthropic

    return anthropic.Anthropic(api_key=cfg.anthropic_api_key)


def _openai(cfg: Config):
    if not cfg.openai_api_key:
        raise ConfigError("OPENAI_API_KEY is required for an openai: model")
    import openai

    return openai.OpenAI(api_key=cfg.openai_api_key)


# ── text completion ──────────────────────────────────────────────────────────

def complete_text(
    cfg: Config, model_spec: str, system: str, user: str, max_tokens: int = 1200
) -> str:
    provider, model = parse_spec(model_spec)
    if provider == "anthropic":
        client = _anthropic(cfg)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
    client = _openai(cfg)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (resp.choices[0].message.content or "").strip()


# ── JSON completion with schema validation ───────────────────────────────────

def complete_json(
    cfg: Config,
    model_spec: str,
    system: str,
    user: str,
    schema: dict,
    max_tokens: int = 400,
) -> dict:
    """Return a JSON object validated against ``schema`` (required keys + enums).

    Uses a prompt-based JSON instruction (works across all SDK/model versions),
    parses tolerantly, validates in code, and retries once before raising.
    """
    provider, model = parse_spec(model_spec)
    sys_prompt = (
        system
        + "\n\nRespond with ONLY a JSON object matching this schema — no prose, "
        "no code fences:\n" + json.dumps(schema)
    )

    def _one_call() -> dict:
        if provider == "anthropic":
            client = _anthropic(cfg)
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=sys_prompt,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(
                b.text for b in resp.content if getattr(b, "type", None) == "text"
            )
        else:
            client = _openai(cfg)
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user},
                ],
            )
            text = resp.choices[0].message.content or ""
        obj = _extract_json(text)
        validate(obj, schema)
        return obj

    try:
        return _one_call()
    except (LLMOutputError, ValueError, KeyError):
        return _one_call()  # one retry; a second failure propagates to the caller


def validate(obj: dict, schema: dict) -> None:
    """Minimal validation: object-ness, required keys, and enum membership."""
    if not isinstance(obj, dict):
        raise LLMOutputError("expected a JSON object")
    for key in schema.get("required", []):
        if key not in obj:
            raise LLMOutputError(f"missing required key: {key}")
    for key, spec in schema.get("properties", {}).items():
        if key in obj and "enum" in spec and obj[key] not in spec["enum"]:
            raise LLMOutputError(f"{key}={obj[key]!r} not in {spec['enum']}")
