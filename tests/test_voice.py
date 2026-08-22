"""Voice layer: composes prose, but always falls back to the template safely."""

from dataclasses import replace

from ernest import voice
from ernest.config import Config

_CFG = Config(triage_model="openai:x", openai_api_key="k")


def test_compose_uses_model_output(monkeypatch):
    monkeypatch.setattr(voice, "complete_text", lambda *a, **k: "Good morning — quiet day.")
    out = voice.compose(_CFG, "Write his brief.", "Nothing flagged.", "FALLBACK")
    assert out == "Good morning — quiet day."


def test_compose_falls_back_when_disabled(monkeypatch):
    monkeypatch.setattr(voice, "complete_text",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    cfg = replace(_CFG, voice=False)
    assert voice.compose(cfg, "i", "facts", "FALLBACK") == "FALLBACK"


def test_compose_falls_back_on_empty_facts(monkeypatch):
    monkeypatch.setattr(voice, "complete_text",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert voice.compose(_CFG, "i", "   ", "FALLBACK") == "FALLBACK"


def test_compose_falls_back_on_model_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(voice, "complete_text", boom)
    assert voice.compose(_CFG, "i", "facts", "FALLBACK") == "FALLBACK"


def test_compose_falls_back_on_empty_output(monkeypatch):
    monkeypatch.setattr(voice, "complete_text", lambda *a, **k: "   ")
    assert voice.compose(_CFG, "i", "facts", "FALLBACK") == "FALLBACK"


def test_voice_model_override_used(monkeypatch):
    seen = {}
    def fake(cfg, model, system, user, max_tokens=500):
        seen["model"] = model
        return "ok"
    monkeypatch.setattr(voice, "complete_text", fake)
    cfg = replace(_CFG, voice_model="anthropic:claude-haiku-4-5")
    voice.compose(cfg, "i", "facts", "FB")
    assert seen["model"] == "anthropic:claude-haiku-4-5"
