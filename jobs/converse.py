"""Talk to Ernest out loud — V0 of the voice puck, on any mic (the M2 laptop).

Push-to-talk conversation loop:

    press Enter → speak → press Enter → Ernest transcribes, thinks, and speaks back

It wires the pieces that already exist into one spoken turn:

    mic → speech.transcribe → bot.route/classify → capability → speech.synthesize → afplay
                                     └── the same intent router the Discord bot uses ──┘

Read-style intents (ask, agenda, research, chat, notes, meetings, status, remember)
run for real. Creating a calendar event runs too, but behind a spoken confirm-gate:
Ernest reads the event back and does nothing until you say "yes" (nothing is
written on a "no" or an unclear answer). The session also carries a few turns of
context, so follow-ups like "make it 4pm" or "add it" resolve. Priority steering
still routes to Discord.

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
import re
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

from ernest import speech
from ernest.audit import log_event
from ernest.config import Config, load

_SAMPLE_RATE = 16_000  # what Whisper wants; mono
_VOICE_SESSION = 0  # stable channel id so _chat_sync keeps this session's history

# Farewell phrases that end the loop without a round-trip to a model.
_BYES = ("goodbye", "good bye", "that's all", "thats all", "stop listening", "never mind")

# A leading wake-word fragment Whisper often keeps ("Harvis, what's…"). Stripped
# before routing so it doesn't pollute the command. Only ever at the very start.
_WAKE_TAIL = re.compile(
    r"^\s*(hey\s+|hi\s+|okay\s+|ok\s+)?"
    r"(jarvis|jarvitz|jervis|arvis|harvis|ernest|earnest|honest)\b[\s,.:!-]*",
    re.IGNORECASE,
)
# Spoken yes/no for confirming a write. Checked as whole words; NO wins ties.
_YES = ("yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "do it",
        "go ahead", "book it", "please do", "affirmative", "correct",
        "sounds good", "okay", "ok", "add it", "please")
_NO = ("no", "nope", "nah", "cancel", "don't", "dont", "drop it", "forget it",
       "negative", "stop", "never mind", "nevermind", "scratch that")


def _strip_wake(text: str) -> str:
    cleaned = _WAKE_TAIL.sub("", text, count=1).strip()
    return cleaned or text  # never blank out a command that was only the wake word


def _yesno(text: str) -> str | None:
    low = text.strip().lower().rstrip(".!?")
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in _NO):
        return "no"
    if any(re.search(rf"\b{re.escape(w)}\b", low) for w in _YES):
        return "yes"
    return None


# ── conversational session: recent turns + a write awaiting a spoken yes/no ───

@dataclass
class _Session:
    history: list = field(default_factory=list)  # recent (speaker, text) turns
    pending: int | None = None                   # action id awaiting yes/no
    pending_desc: str = ""                        # what we're confirming (for re-asks)

    def add(self, speaker: str, text: str) -> None:
        self.history.append((speaker, text))
        del self.history[:-6]  # keep only the last few turns

    def context(self) -> str:
        return "\n".join(f"{who}: {what}" for who, what in self.history)


# ── dispatch ─────────────────────────────────────────────────────────────────

def respond(cfg: Config, command: str, arg: str) -> str:
    """Run one READ intent and return what Ernest should say. Writes are handled
    upstream in _process (spoken confirm-gate), never here."""
    from ernest import bot

    if command == "help":
        return ("You can ask me anything, ask what's on your calendar, add an event, "
                "tell me to remember something, or say research and a topic.")
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
    if command == "steer":  # persistent priority rule — still via Discord for now
        return "Changing how I prioritize email still goes through Discord — tell me there."
    return bot._ask_sync(cfg, arg)  # default: retrieval Q&A


def _process(cfg: Config, session: _Session, heard: str, speak) -> None:
    """Handle one recognized (already wake-stripped) utterance. ``speak`` voices
    each reply. Resolves a pending confirmation, gates writes, or answers reads."""
    from ernest import bot

    # 1) Resolving a write we already proposed?
    if session.pending is not None:
        verdict = _yesno(heard)
        if verdict == "yes":
            result = bot._decide_sync(cfg, str(session.pending), True)
            session.pending = None
            speak(result)
        elif verdict == "no":
            bot._decide_sync(cfg, str(session.pending), False)
            session.pending = None
            speak("Okay, I'll leave it.")
        else:  # unclear — keep waiting
            speak(f"{session.pending_desc} Yes or no?")
        return

    # 2) Route + classify, giving the router recent context so follow-ups resolve.
    command, arg = bot.route(heard)
    if command == "chat":
        command, arg = bot.classify(cfg, arg, context=session.context())
    log_event("converse", "intent", {"command": command})
    session.add("You", heard)

    # 3) Writes → propose, then a spoken confirm-gate before anything happens.
    if command == "event":
        reply, action_id = bot._propose_event_sync(cfg, arg)
        if action_id is None:
            speak(reply)  # couldn't parse or no calendar access — just say why
            return
        prompt = reply.split("\n", 1)[0]  # first line: "I'd add "X" on WHEN."
        session.pending, session.pending_desc = action_id, prompt
        speak(f"{prompt} Should I put it on your calendar?")
        return
    if command in ("approve", "deny"):
        speak(bot._decide_sync(cfg, arg, command == "approve"))
        return

    # 4) Reads.
    answer = respond(cfg, command, arg)
    session.add("Ernest", answer)
    speak(answer)


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
    is_path = ("/" in cfg.wake_model or cfg.wake_model.endswith((".onnx", ".tflite")))
    if not is_path:  # a bundled model name — fetch its weights once
        try:
            openwakeword.utils.download_models([cfg.wake_model])
        except Exception:
            pass  # already present; Model() will report a real error if not
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


def _wake_loop(cfg: Config, workdir: Path, session: _Session, debug: bool = False) -> None:
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
                _handle_utterance(cfg, wav, workdir, session)
                # If a write is awaiting yes/no, listen right away — no wake word.
                tries = 0
                while session.pending is not None and tries < 3:
                    tries += 1
                    subprocess.Popen(["afplay", cfg.wake_ack_sound])
                    while not q.empty():
                        q.get_nowait()
                    if not _capture_utterance(cfg, q, wav):
                        break
                    _handle_utterance(cfg, wav, workdir, session)
                if session.pending is not None:  # gave up waiting for a clear answer
                    session.pending = None
                    _speak(cfg, "I'll leave that for now.", workdir)
            else:
                print("(didn't catch a command)")
            # Discard everything captured during processing + playback (Ernest's
            # own voice, the chime) so it can't re-trigger the wake word.
            oww.reset()
            buf = np.empty(0, dtype="int16")
            preroll.clear()
            while not q.empty():
                q.get_nowait()
            print(f"\nListening for '{cfg.wake_model}'…")


# ── entrypoints ──────────────────────────────────────────────────────────────

def _handle_utterance(cfg: Config, wav: Path, workdir: Path, session: _Session) -> bool:
    """Transcribe one captured clip and act on it. False = caller should stop."""
    heard = speech.transcribe(cfg, wav)
    if not heard:
        print("(couldn't make that out)")
        return True
    print(f"🗣️  {heard}")
    clean = _strip_wake(heard)
    # A farewell only ends the loop when we're not mid-confirmation.
    if session.pending is None and clean.strip().lower().rstrip(".!") in _BYES:
        _speak(cfg, "Talk soon.", workdir)
        return False
    _process(cfg, session, clean, lambda t: _speak(cfg, t, workdir))
    return True


def _one_turn(cfg: Config, workdir: Path, session: _Session) -> bool:
    """Push-to-talk: capture → handle. Returns False to end the loop."""
    prompt = "Yes or no?… " if session.pending is not None else "Press Enter to talk (Ctrl-C to quit)… "
    input(f"\n{prompt}")
    wav = workdir / "turn.wav"
    if not _record_wav(wav):
        print("(heard nothing)")
        return True
    return _handle_utterance(cfg, wav, workdir, session)


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
    session = _Session()
    with tempfile.TemporaryDirectory(prefix="ernest-voice-") as tmp:
        workdir = Path(tmp)
        if args.say is not None:
            _speak(cfg, args.say, workdir)
            return
        if args.text is not None:
            _process(cfg, session, _strip_wake(args.text), lambda t: _speak(cfg, t, workdir))
            return
        if args.wake:
            try:
                _wake_loop(cfg, workdir, session, debug=args.debug)
            except (KeyboardInterrupt, EOFError):
                print("\nStopped.")
            return
        print("Ernest is listening. Say 'goodbye' to stop.")
        try:
            while _one_turn(cfg, workdir, session):
                if args.once:
                    break
        except (KeyboardInterrupt, EOFError):
            print("\nStopped.")


if __name__ == "__main__":
    main()
