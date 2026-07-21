# Phase 2 — Local MLX models on the Mac

Goal: replace LiveKit Cloud Inference with local, MLX-backed models running on this
Apple-Silicon Mac, **one component at a time**, verifying after each swap.

> Status legend: ✅ verified (installed code / official docs / real GitHub) · 🧩 decision needed
> · ⚠️ risk to validate empirically. Every non-obvious claim below was checked against the
> installed package source, docs.livekit.io, real GitHub READMEs, PyPI, or Hugging Face.

---

## Target hardware (✅)

| | |
|---|---|
| Machine | MacBookPro18,2 — **Apple M1 Max** |
| CPU / GPU | 10-core CPU (8P+2E) · 32-core GPU · Metal 4 |
| Unified memory | **32 GB** ← the real constraint (OS + agent + every loaded model share it) |
| Disk free | ~206 GB |

**Latency rule of thumb (M1 Max, 4-bit, NOT benchmarked — measure locally):**
~4–8B ≈ snappy · ~12–14B ≈ acceptable · ~26–31B ≈ likely too slow for smooth voice.

---

## Correction to the original premise (✅ HIGH)

The app is **not** fully cloud-hosted. `inference.VAD(model="silero")` **already runs locally**
— backed by the native `livekit-local-inference` package (`.provider == "livekit-local-inference"`,
seen in `.venv/.../livekit/agents/inference/vad.py`). Only `inference.STT`, `inference.LLM`,
`inference.TTS` route to LiveKit's hosted gateway (`inference/llm.py` uses
`get_default_inference_url` + `create_access_token`). **So only STT / LLM / TTS need replacing.**

---

## Phase 1 baseline (what we're replacing)

`hotel_receptionist/agent.py` (the four model slots):
```python
vad=inference.VAD(model="silero"),         # already local — KEEP
stt=inference.STT("deepgram/nova-3"),      # cloud — replace LAST
llm=inference.LLM("google/gemma-4-31b-it"),# cloud — replace (tool-calling risk ⚠️)
tts=inference.TTS("inworld/inworld-tts-2"),# cloud — replace (low risk)
```

---

## Installed for Phase 2

| Package | Version | Purpose | Status |
|---|---|---|---|
| `mlx` / `mlx-metal` | 0.32.0 | Apple MLX runtime (Metal GPU) | ✅ installed |
| `mlx-lm` | 0.31.3 | MLX LLM runner + OpenAI-compatible `mlx_lm.server` | ✅ installed |
| `livekit-plugins-openai` | 1.6.6 | Point LiveKit at any OpenAI-compatible `base_url` | ✅ installed |
| `livekit-plugins-silero` | 1.6.x | Local VAD (already used via native inference) | ✅ installed |
| `livekit-plugins-turn-detector` | 1.6.x | Local end-of-turn model (CPU, <500 MB) | ✅ installed |
| `mlx-audio` | — | MLX TTS+STT server (`/v1/audio/speech`, `/v1/audio/transcriptions`) | ⬜ install at TTS step |

> Installing `livekit-plugins-openai` bumped `livekit-agents` 1.6.5 → **1.6.6** (compatible).

---

## Verified integration surface

### MLX LLM server (`mlx-lm`) — ✅ HIGH
```bash
python -m mlx_lm.server --model <hf-repo-or-path> --host 127.0.0.1 --port 8080
# OpenAI-compatible /v1/chat/completions, supports stream:true. Default 127.0.0.1:8080.
# Docs: github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md ("basic security only")
```

### LiveKit → local OpenAI-compatible endpoints (`livekit-plugins-openai 1.6.6`) — ✅ HIGH
```python
from livekit.plugins import openai

llm = openai.LLM(model="<served-model>", base_url="http://localhost:8080/v1", api_key="not-needed")
tts = openai.TTS(model="<tts-model>", voice="<voice>", base_url="http://localhost:8000/v1",
                 api_key="not-needed", response_format="wav")     # -> /v1/audio/speech
stt = openai.STT(model="<asr-model>", base_url="http://localhost:8000/v1", api_key="not-needed",
                 use_realtime=False)                              # -> /v1/audio/transcriptions
```
- `base_url` is the canonical path for any OpenAI-compatible server (LiveKit docs:
  models/llm/openai-compatible-llms/). Ignore `with_ollama` — use `base_url` directly.
- **Do NOT set `use_realtime=True`** on `openai.STT` against a local server (that's OpenAI's
  realtime websocket). Default `use_realtime=False` uses the REST `/v1/audio/transcriptions`.
- A LiveKit docs page wrongly implies STT `base_url` is "Node-only" — **the Python source
  disproves that** (`stt.py` accepts `base_url`). ✅ HIGH.

### Non-streaming auto-wrap (✅ HIGH)
LiveKit auto-wraps a non-streaming TTS with `tts.StreamAdapter` (sentence-tokenized) and a
non-streaming STT with `stt.StreamAdapter(stt=..., vad=...)` — **the STT wrap requires a VAD**
(we have one). Confirmed in `.venv/.../voice/agent.py` and `.../stt/stream_adapter.py`.

### Local VAD / Turn detection (✅ HIGH)
```python
from livekit.plugins import silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel  # or .english.EnglishModel
vad = silero.VAD.load()                     # optional; current native VAD is already local
turn_detection = MultilingualModel()        # CPU, <500MB; model via `download-files`
```
> In 1.6.x, `turn_detection=` on `AgentSession` still works but is deprecated in favor of
> `turn_handling=TurnHandlingOptions(turn_detection=...)`. Either works today.

---

## LLM model options 🧩 (verified repo IDs on HF `mlx-community`)

| HF repo ID | Approx 4-bit footprint* | Notes |
|---|---|---|
| **`mlx-community/Qwen3-8B-4bit`** (or `Qwen3-4B-4bit`) | ~5 GB | **Safest tool-calling** (Qwen parser supported by `mlx_lm.server`). Best for this tool-heavy app. |
| `mlx-community/gemma-4-12B-it-4bit` (or `-qat-4bit`) | ~7 GB | Demo's Gemma family, snappy. Tool-calling via `mlx_lm.server` **less proven** ⚠️. |
| `mlx-community/gemma-4-26b-a4b-it-4bit` (MoE) | ~14–15 GB | Higher quality, ~4B active params. |
| `mlx-community/gemma-4-31b-it-4bit` | ~17–18 GB | Exact match to hosted model; likely too slow for snappy voice. |

*Footprints are estimates (~0.55 GB/B @ 4-bit) — MEDIUM confidence. tokens/sec NOT benchmarked.

**⚠️ Tool-calling is the #1 risk for this app.** It has many function tools + `max_tool_steps=5`.
`mlx_lm.server` tool parsers are Qwen-centric (Gemma not listed). Plan: validate tool calls
early; if Gemma misbehaves, fall back to Qwen3. (Alt servers advertising better tool/MCP
support: `cubist38/mlx-openai-server`, `waybarrios/vllm-mlx` — only if needed.)

## TTS (local) — ✅ HIGH, low risk
```bash
pip install mlx-audio
python -m mlx_audio.server --host 127.0.0.1 --port 8000   # OpenAI-compatible /v1/audio/speech
```
```python
tts = openai.TTS(model="mlx-community/Kokoro-82M-bf16", voice="af_heart",
                 base_url="http://localhost:8000/v1", api_key="not-needed", response_format="wav")
```
- `mlx-audio` (github `Blaizzy/mlx-audio`) is MLX-native, OpenAI-compatible; models incl.
  Kokoro (`mlx-community/Kokoro-82M-bf16`/`-8bit`/`-4bit`), Qwen3-TTS, etc.
- Official LiveKit Kokoro example uses non-MLX **Kokoro-FastAPI** (`:8880`, `model="kokoro"`,
  `voice="af_alloy"`) — good fallback if mlx-audio gives trouble.

## STT (local) — ⚠️ hardest, do LAST
```python
stt = openai.STT(model="mlx-community/whisper-large-v3-turbo-asr-fp16",
                 base_url="http://localhost:8000/v1", api_key="not-needed", use_realtime=False)
```
- `mlx-audio` also serves `/v1/audio/transcriptions` (batch Whisper). Works via StreamAdapter +
  our VAD, **but** transcription only fires after each end-of-speech → added latency, no interim
  results. This is the biggest real-time quality hit. **Keep Deepgram nova-3 until last.**
- Streaming local ASR (`parakeet-mlx`, `senstella/parakeet-mlx`) exists but has **no** LiveKit
  plugin — would need a custom `stt.STT` wrapper. Immature; skip for now.

---

## Recommended incremental swap order

1. ~~VAD~~ — **already local. No-op.** ✅
2. **LLM → local MLX** — do this early (it's the point of the exercise *and* surfaces the
   tool-calling risk soonest). `mlx_lm.server` + `openai.LLM(base_url=)`. Keep cloud STT/TTS
   while testing. 🧩 pick model above.
3. **Turn detection → local** — trivial add (`MultilingualModel()`), optional polish.
4. **TTS → local MLX** — `mlx-audio` Kokoro + `openai.TTS(base_url=)`. Low risk.
5. **STT → local MLX** ✅ — used **Qwen3-ASR** (not Whisper) via a custom in-process plugin
   `hotel_receptionist/local_stt.py`, because mlx-audio's *HTTP server* crashes on Qwen3-ASR
   (thread-local MLX stream). Non-streaming → auto StreamAdapter + session VAD. Hardest; last.

> (Pure-risk order would put TTS before LLM, but doing LLM first de-risks the whole plan by
> exposing the tool-calling question immediately — and it's what we most want to prove.)

---

## Fabrications from the old Copilot notes — DO NOT USE
- **`simplismart` TTS plugin** — does not exist. Simplismart is a real LiveKit *LLM* partner, not a TTS plugin.
- **`nemotron-3-asr` local STT** — no such plugin/model. Real local ASR = `mlx-whisper` / `mlx-audio` Whisper / `parakeet-mlx`.

## Not fully verified (honest flags)
- tokens/sec for any MLX LLM on this M1 Max — **not benchmarked; measure it.**
- `mlx_lm.server` tool-calling **with Gemma specifically** — MEDIUM/LOW; test empirically.
- Exact memory footprints — estimates (MEDIUM).

---

## Changelog
- **2026-07-21** — Phase 2 started. Verified hardware; installed `mlx-lm`, `mlx`,
  `livekit-plugins-openai`. Confirmed (against installed code + official sources): VAD already
  local; LLM/STT/TTS `base_url` support; `mlx_lm.server`; `mlx-audio` OpenAI-compatible
  TTS/STT; StreamAdapter auto-wrap; verified `mlx-community` model IDs. Identified tool-calling
  as the key LLM risk (favor Qwen3). Set swap order LLM → turn-detect → TTS → STT.
- **2026-07-21 (later)** — **LLM swapped to local MLX ✅.** Downloaded `mlx-community/Qwen3-8B-4bit`
  (~5 GB, peak **4.7 GB**, **64.7 tok/s** on M1 Max). Ran `mlx_lm.server` on :8080; verified
  OpenAI-style **tool-calling works** (`book_room` returned correct args, `finish_reason=tool_calls`)
  and **thinking is disabled** via `extra_body={"chat_template_kwargs":{"enable_thinking":False}}`
  (no `<think>`). Wired `agent.py` with a `_build_llm()` env toggle (`LLM_BACKEND=local`, default
  cloud); activated in `.env.local`. STT + TTS still cloud. **Next: TTS → local (mlx-audio Kokoro).**
- **2026-07-21 (later 2)** — **TTS swapped to local MLX ✅.** `mlx-audio` server on :8000 + Kokoro
  (`mlx-community/Kokoro-82M-bf16`, voice `af_heart`, 24 kHz). **Gotcha solved:** LiveKit's
  `openai.TTS` uses an SSE transport for any non-OpenAI model id, but mlx-audio returns *raw audio
  bytes* → wrapped in a tiny `openai.TTS` subclass that forces `AudioChunkedStream` (verified: 19
  frames / 2.9 s decoded, both wav & pcm). Wired `agent.py` `_build_tts()` env toggle
  (`TTS_BACKEND=local`, default cloud). Local deps captured in `requirements-local.txt` (mlx-audio,
  uvicorn/fastapi, webrtcvad, misaki[en], `setuptools<80` for `pkg_resources`). STT still cloud.
  **Next: STT → local (mlx-audio Whisper) — the last and hardest.**
- **2026-07-21 (later 3)** — **STT swapped to local MLX ✅ — the agent is now FULLY LOCAL.** Used
  **Qwen3-ASR** (`mlx-community/Qwen3-ASR-1.7B-8bit`) per request. **Gotcha solved:** mlx-audio's
  HTTP server crashes on Qwen3-ASR — `RuntimeError: no Stream(gpu, 0) in current thread` (MLX
  streams are thread-local; the server loads on one thread and generates on another). Fix: a custom
  in-process LiveKit STT plugin (`local_stt.py` → `MLXQwen3STT`) that loads **and** runs on ONE
  dedicated worker thread — so **no STT server process is needed**. Non-streaming → AgentSession
  wraps it with StreamAdapter + the session VAD. Verified end-to-end (WAV→plugin→FINAL_TRANSCRIPT,
  exact text; ~1.1 s for 4.4 s audio). Toggle `STT_BACKEND=local`. **Phase 2 COMPLETE:
  VAD (native) + LLM (Qwen3-8B) + TTS (Kokoro) + STT (Qwen3-ASR) all local on the M1 Max.**
