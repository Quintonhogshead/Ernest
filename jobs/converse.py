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
    python -m jobs.converse --wake          # hands-free: "hey jarvis" then a command
    python -m jobs.converse                 # interactive push-to-talk loop
    python -m jobs.converse --once          # a single turn, then exit
    python -m jobs.converse --text "what's on my calendar tomorrow"   # skip the mic
    python -m jobs.converse --say "hello"   # TTS smoke test only

Needs a mic and, for playback, macOS `afplay`. Audio capture uses sounddevice;
the wake word adds openWakeWord + a VAD endpointer:
    pip install sounddevice numpy                 # push-to-talk
    pip install openwakeword onnxruntime webrtcvad # hands-free (--wake)
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


# ── hands-free: wake word + voice-activity endpointing ───────────────────────

_FRAME_MS = 20
_FRAME = _SAMPLE_RATE * _FRAME_MS // 1000  # 320 samples @16k = one 20ms frame
_OWW_CHUNK = 1280  # openWakeWord wants 80ms (4 frames) per predict
_END_SILENCE_MS = 800  # trailing silence that ends an utterance
_LEAD_TIMEOUT_MS = 3000  # give up if no speech starts after the wake word
_MAX_UTTERANCE_MS = 15_000
_PREROLL_MS = 300  # audio kept from before the wake trigger, so onsets aren't clipped


def _load_wakeword(cfg: Config):
    """Build the openWakeWord model, downloading the bundled weights on first run."""
    try:
        import openwakeword
        from openwakeword.model import Model
    except ImportError:
        print("Wake word needs: pip install openwakeword onnxruntime webrtcvad",
              file=sys.stderr)
        raise SystemExit(2)
    try:  # bundled models download once; a path to a custom .onnx is used as-is
        openwakeword.utils.download_models([cfg.wake_model])
    except Exception:
        pass  # already present, or a custom path — Model() will report a real error
    return Model(wakeword_models=[cfg.wake_model], inference_framework="onnx")


def _capture_utterance(cfg: Config, q, out_path: Path, seed: list | None = None) -> bool:
    """After a wake, pull frames until trailing silence; write a WAV. False if silent.

    ``seed`` is a short pre-roll of frames captured just before/around the wake
    trigger, prepended so the onset of the command isn't clipped.
    """
    import numpy as np
    import webrtcvad

    vad = webrtcvad.Vad(1)  # least aggressive: keeps quiet onsets/consonants
    frames: list = list(seed or [])
    started = False
    silent_ms = lead_ms = 0
    while len(frames) * _FRAME_MS < _MAX_UTTERANCE_MS:
        frame = q.get().reshape(-1)
        speech_here = vad.is_speech(frame.tobytes(), _SAMPLE_RATE)
        if speech_here:
            started, silent_ms = True, 0
            frames.append(frame)
        elif started:
            silent_ms += _FRAME_MS
            frames.append(frame)
            if silent_ms >= _END_SILENCE_MS:
                break
        else:  # still waiting for the user to start talking
            lead_ms += _FRAME_MS
            if lead_ms >= _LEAD_TIMEOUT_MS:
                return False
    if not started:
        return False
    audio = np.concatenate(frames, axis=0)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        wf.writeframes(audio.tobytes())
    return True


def _wake_loop(cfg: Config, workdir: Path, debug: bool = False) -> None:
    """Listen continuously; on the wake word, capture a command and answer it."""
    import queue

    import numpy as np
    import sounddevice as sd

    from collections import deque

    oww = _load_wakeword(cfg)
    q: "queue.Queue" = queue.Queue()
    stream = sd.InputStream(
        samplerate=_SAMPLE_RATE, channels=1, dtype="int16", blocksize=_FRAME,
        callback=lambda data, *_: q.put(data.copy()),
    )
    dev = sd.query_devices(kind="input")
    print(f"Input device: {dev['name']}")
    print(f"Listening for the wake word ('{cfg.wake_model}'). Ctrl-C to stop.")
    if debug:
        print("[debug] showing mic level (rms) and wake score — say the wake word.")
    buf = np.empty(0, dtype="int16")
    preroll: deque = deque(maxlen=_PREROLL_MS // _FRAME_MS)  # recent frames
    with stream:
        while True:
            frame = q.get().reshape(-1)
            preroll.append(frame)
            buf = np.concatenate([buf, frame])
            if len(buf) < _OWW_CHUNK:
                continue
            chunk, buf = buf[:_OWW_CHUNK], buf[_OWW_CHUNK:]
            score = max(oww.predict(chunk).values())
            if debug:
                rms = int(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                if rms > 150 or score > 0.05:  # only print when there's signal
                    print(f"[debug] rms={rms:<6} score={score:.3f}")
            if score < cfg.wake_threshold:
                continue
            # Triggered: chime (non-blocking so capture starts instantly) and
            # capture the command, seeded with the pre-roll so its onset survives.
            log_event("converse", "wake", {"score": round(float(score), 3)})
            subprocess.Popen(["afplay", cfg.wake_ack_sound])
            seed = list(preroll)
            oww.reset()
            buf = np.empty(0, dtype="int16")
            preroll.clear()
            wav = workdir / "utter.wav"
            if _capture_utterance(cfg, q, wav, seed=seed):
                _handle_utterance(cfg, wav, workdir)
            else:
                print("(didn't catch a command)")
            print(f"\nListening for '{cfg.wake_model}'…")


# ── entrypoints ──────────────────────────────────────────────────────────────

def _handle_utterance(cfg: Config, wav: Path, workdir: Path) -> bool:
    """Transcribe one captured clip, respond, and speak. False = caller should stop."""
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


def _one_turn(cfg: Config, workdir: Path) -> bool:
    """Push-to-talk: capture → handle. Returns False to end the loop."""
    input("\nPress Enter to talk (Ctrl-C to quit)… ")
    wav = workdir / "turn.wav"
    if not _record_wav(wav):
        print("(heard nothing)")
        return True
    return _handle_utterance(cfg, wav, workdir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Talk to Ernest (voice).")
    parser.add_argument("--wake", action="store_true",
                        help="hands-free: listen for the wake word continuously")
    parser.add_argument("--debug", action="store_true",
                        help="with --wake: print mic level and wake score live")
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
        if args.wake:
            try:
                _wake_loop(cfg, workdir, debug=args.debug)
            except (KeyboardInterrupt, EOFError):
                print("\nStopped.")
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
