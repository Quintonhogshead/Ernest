# A custom "Hey Ernest" wake word

The hands-free loop (`python -m jobs.converse --wake`) ships pointed at
openWakeWord's bundled **`hey_jarvis`** model. To wake on **"Hey Ernest"**
instead, you train a small custom model and point `ERNEST_WAKE_MODEL` at it.

openWakeWord models are trained on *synthetic* speech — you don't record
hundreds of samples yourself. A TTS engine (Piper) generates thousands of
"hey ernest" clips across voices/accents/speeds, mixed with noise and negative
audio, and a small classifier learns the phrase. It runs on the openWakeWord
**automatic training notebook**; a laptop CPU is slow but a free Colab GPU does
it in well under an hour.

## Steps

1. Open the official notebook:
   https://github.com/dscripka/openWakeWord → `notebooks/automatic_model_training.ipynb`
   (there is a "Open in Colab" badge; pick a GPU runtime).
2. Set the target phrase to `hey ernest` (try a couple of spellings/pronunciations
   as separate variants if detection is weak, e.g. `hey ernest`, `hey earnest`).
3. Run the notebook end to end. It synthesizes positives with Piper, pulls the
   negative/background sets, trains, and validates.
4. Download the resulting **`hey_ernest.onnx`** (the ONNX export, not the tflite,
   to match our `inference_framework="onnx"`).

## Wire it in

Drop the file somewhere stable and point the config at its **full path**
(`ernest/config.py` already treats a path-valued `wake_model` as a custom model,
and `_load_wakeword` skips the bundled-model download for it):

```bash
# ~/Desktop/Ernest/.env
ERNEST_WAKE_MODEL=/Users/quintonjohnson/Desktop/Ernest/state/wake/hey_ernest.onnx
```

Then:

```bash
python -m jobs.converse --wake --debug
```

Say "hey ernest" and watch the `score`. Tune with:

- `ERNEST_WAKE_THRESHOLD` — raise toward `0.6`–`0.7` if it false-triggers on
  ordinary speech; lower toward `0.4` if it misses you.
- If it's consistently weak, retrain with more phrase variants or more
  augmentation rounds in the notebook.

## On the Pi later

The same `.onnx` runs unchanged on the Raspberry Pi — copy it over and set the
same `ERNEST_WAKE_MODEL`. onnxruntime is the only heavy dep the puck needs for
detection.
