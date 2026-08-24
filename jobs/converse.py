"""Talk to Ernest out loud — V0 of the voice puck, on any mic (the M2 laptop).

Push-to-talk conversation loop:

    press Enter → speak → press Enter → Ernest transcribes, thinks, and speaks back

It wires the pieces that already exist into one spoken turn:

    mic → speech.transcribe → bot.route/classify → capability → speech.synthesize → afplay
                                     └── the same intent router the Discord bot uses ──┘

Read-style intents (ask, agenda, research, chat, notes, meetings, status, remember)
run for real. Write/send intents (create an event, steer priority, approve/deny)
are NOT executed by voice yet — Ernest says so and points you at Discord, so the
approval discipline the text bot enforces isn't bypassed by talking.

Usage:
    python -m jobs.converse                 # interactive push-to-talk loop
    python -m jobs.converse --once          # a single turn, then exit
    python -m jobs.converse --text "what's on my calendar tomorrow"   # skip the mic
    python -m jobs.converse --say "hello"   # TTS smoke test only

Needs a mic and, for playback, macOS `afplay`. Audio capture uses sounddevice:
    pip install sounddevice numpy
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

from ernest import speech
from ernest.audit import log_event
from ernest.config import Config, load

_SAMPLE_RATE = 16_000  # what Whisper wants; mono
_VOICE_SESSION = 0  # stable channel id so _chat_sync keeps this session's history

# Farewell phrases that end the loop without a round-trip to a model.
_BYES = ("goodbye", "good bye", "that's all", "thats all", "stop listening", "never mind")


# ── dispatch: map a routed intent to spoken text ─────────────────────────────

def respond(cfg: Config, command: str, arg: str) -> str:
    """Run one routed intent and return what Ernest should say."""
    # Imported here so the heavy Discord module loads only when we actually talk.
    from ernest import bot

    if command == "help":
        return ("You can ask me anything, ask what's on your calendar, tell me to "
                "remember something, or say research and a topic. Creating events "
                "and sending mail still go through Discord for approval.")
    if command == "remember":
        if not arg:
            return "What should I remember?"
        bot._remember_sync(cfg, arg)
        return "Noted. Consider it remembered."
    if command == "notes":
        return bot._notes_sync(cfg)
    if command == "meetings":
        return bot._meetings_sync(cfg)
    if command == "meeting_search":
        return bot._meeting_search_sync(cfg, arg) if arg else "Which meeting?"
    if command == "status":
        return bot._status_sync(cfg)
    if command == "agenda":
        return bot._agenda_sync(cfg, arg)
    if command == "research":
        return bot._research_sync(cfg, arg) if arg else "Give me a topic to research."
    if command == "chat":
        return bot._chat_sync(cfg, _VOICE_SESSION, arg)
    # Write/send intents: acknowledged but not executed by voice in V0.
    if command in ("event", "steer", "approve", "deny"):
        return ("That one changes your accounts, so I've left it for Discord where "
                "you can approve it. Ask me to do it there.")
    return bot._ask_sync(cfg, arg)  # default: retrieval Q&A


def handle_text(cfg: Config, text: str) -> str:
    """Route a line of text through the same parser+router the bot uses."""
    from ernest import bot

    command, arg = bot.route(text)
    if command == "chat":
        command, arg = bot.classify(cfg, arg)
    log_event("converse", "intent", {"command": command})
    return respond(cfg, command, arg)


# ── audio in / out ───────────────────────────────────────────────────────────

def _record_wav(out_path: Path) -> bool:
    """Record from the default mic until Enter; write a 16k mono WAV. False if silent."""
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        print("Mic capture needs: pip install sounddevice numpy", file=sys.stderr)
        raise SystemExit(2)

    frames: list = []
    with sd.InputStream(samplerate=_SAMPLE_RATE, channels=1, dtype="int16",
                        callback=lambda data, *_: frames.append(data.copy())):
        input("🎙️  Listening — press Enter when you're done… ")

    if not frames:
        return False
    audio = np.concatenate(frames, axis=0)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return True


def _speak(cfg: Config, text: str, workdir: Path) -> None:
    """Synthesize and play ``text`` (best effort — never crash the loop on audio)."""
    print(f"\n🤖 {text}\n")
    try:
        mp3 = speech.synthesize(cfg, text, workdir / "reply.mp3")
        subprocess.run(["afplay", str(mp3)], check=False)
    except Exception as exc:  # missing key, network, no afplay — text already printed
        log_event("converse", "speak_failed", {"error": str(exc)})


# ── entrypoints ──────────────────────────────────────────────────────────────

def _one_turn(cfg: Config, workdir: Path) -> bool:
    """Capture → transcribe → respond → speak. Returns False to end the loop."""
    input("\nPress Enter to talk (Ctrl-C to quit)… ")
    wav = workdir / "turn.wav"
    if not _record_wav(wav):
        print("(heard nothing)")
        return True
    heard = speech.transcribe(cfg, wav)
    if not heard:
        print("(couldn't make that out)")
        return True
    print(f"🗣️  {heard}")
    if heard.strip().lower().rstrip(".!") in _BYES:
        _speak(cfg, "Talk soon.", workdir)
        return False
    _speak(cfg, handle_text(cfg, heard), workdir)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to Ernest (voice V0).")
    parser.add_argument("--once", action="store_true", help="one turn, then exit")
    parser.add_argument("--text", help="skip the mic; route this text and speak the reply")
    parser.add_argument("--say", help="TTS smoke test: just speak this text")
    args = parser.parse_args()

    cfg = load()
    with tempfile.TemporaryDirectory(prefix="ernest-voice-") as tmp:
        workdir = Path(tmp)
        if args.say is not None:
            _speak(cfg, args.say, workdir)
            return
        if args.text is not None:
            _speak(cfg, handle_text(cfg, args.text), workdir)
            return
        print("Ernest is listening. Say 'goodbye' to stop.")
        try:
            while _one_turn(cfg, workdir):
                if args.once:
                    break
        except (KeyboardInterrupt, EOFError):
            print("\nStopped.")


if __name__ == "__main__":
    main()
