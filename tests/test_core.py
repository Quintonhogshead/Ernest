"""Tests that run with no external SDKs, no network, and no credentials."""

import os
import struct

import pytest

from ernest import ConfigError
from ernest.config import Config, load, require
from ernest.embed import cosine, pack, unpack
from ernest.llm import LLMOutputError, parse_spec, validate, _extract_json
from ernest.news import _strip_html
from ernest.imessage import decode
from ernest import triage


def test_parse_spec_ok():
    assert parse_spec("anthropic:claude-haiku-4-5") == ("anthropic", "claude-haiku-4-5")
    assert parse_spec("openai:gpt-5.1-mini") == ("openai", "gpt-5.1-mini")


def test_parse_spec_bad():
    with pytest.raises(ConfigError):
        parse_spec("claude-haiku-4-5")
    with pytest.raises(ConfigError):
        parse_spec("cohere:embed")


def test_extract_json_tolerates_fences_and_prose():
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('Here you go: {"a": 1} done') == {"a": 1}
    with pytest.raises(LLMOutputError):
        _extract_json("no json here")


def test_validate_enum_and_required():
    schema = {"required": ["category"],
              "properties": {"category": {"enum": ["a", "b"]}}}
    validate({"category": "a"}, schema)
    with pytest.raises(LLMOutputError):
        validate({"category": "z"}, schema)
    with pytest.raises(LLMOutputError):
        validate({}, schema)


def test_require_reports_missing():
    cfg = Config()
    with pytest.raises(ConfigError):
        require(cfg, "canvas_token")
    require(cfg, "triage_model")  # has a default → present


def test_config_load_defaults(monkeypatch):
    for k in list(os.environ):
        if k.startswith("ERNEST_") or k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY",
                                            "CANVAS_BASE_URL", "CANVAS_TOKEN"):
            monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("ernest.config.load_dotenv", lambda *a, **k: False)
    cfg = load()
    assert cfg.triage_model == "anthropic:claude-haiku-4-5"
    assert cfg.embed_model.startswith("openai:")
    assert cfg.accounts == ()
    assert cfg.paused is False


def test_config_honors_env_path(monkeypatch, tmp_path):
    # Jobs must read the same .env the dashboard writes (e.g. /data/.env on Fly).
    import os
    env_file = os.path.join(tmp_path, "custom.env")
    open(env_file, "w").write("ERNEST_DISCORD_TOKEN=abc\nERNEST_DISCORD_USER_ID=42\n")
    for k in ("ERNEST_DISCORD_TOKEN", "ERNEST_DISCORD_USER_ID"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ERNEST_ENV_PATH", env_file)
    cfg = load()
    assert cfg.discord_token == "abc"
    assert cfg.discord_user_id == "42"


def test_config_accounts_split(monkeypatch):
    monkeypatch.setattr("ernest.config.load_dotenv", lambda *a, **k: False)
    monkeypatch.setenv("ERNEST_ACCOUNTS", "work, school ,business")
    assert load().accounts == ("work", "school", "business")


def test_vector_math_roundtrip():
    vec = [0.1, -0.2, 0.3, 0.4]
    assert unpack(pack(vec)) == pytest.approx(vec, abs=1e-6)
    assert cosine(vec, vec) == pytest.approx(1.0, abs=1e-6)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([], [1, 2]) == 0.0


def test_strip_html():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert len(_strip_html("x" * 999)) <= 500


def test_imessage_decode_prefers_text():
    assert decode("hi there", None) == "hi there"
    assert decode(None, None) is None


def test_imessage_decode_short_nsstring():
    # NSString marker + 6 bytes + 1-byte length + payload
    payload = b"hello"
    blob = b"\x00\x00NSString" + b"\x00" * 6 + bytes([len(payload)]) + payload
    assert decode(None, blob) == "hello"


def test_triage_wrap_email_shape():
    msg = {"account": "work", "sender": "a@b.com", "subject": "Hi", "date": "today",
           "body_text": "please review"}
    wrapped = triage._wrap_email(msg)
    assert "account=\"work\"" in wrapped
    assert "please review" in wrapped


def test_triage_schema_categories_consistent():
    assert set(triage.SCHEMA["properties"]["category"]["enum"]) == set(triage.CATEGORIES)
