# livekit-nv-models

Self-hosting experiments for the LiveKit [`hotel_receptionist`](hotel_receptionist/README.md)
voice-agent example, worked through in phases:

1. **Phase 1 — LiveKit Cloud Inference** ✅ — models served through LiveKit's
   hosted gateway (`inference.STT/LLM/TTS/VAD` in `agent.py`).
2. **Phase 2 — local MLX models** ✅ — STT/LLM/TTS run on this Apple-Silicon Mac,
   each component individually toggleable. Deep dive: [`phase2-local-mlx.md`](phase2-local-mlx.md).
3. **Phase 3 — remote NVIDIA GPU** box (planned).

Each model slot in `agent.py` is chosen by a `*_BACKEND` env var (default `cloud`), so you can
run all-cloud (Phase 1), all-local (Phase 2), or any mix — just by editing `.env.local`.

---

## Phase 1 — how to run & validate

### Prerequisites (one-time, already done)

- Python **3.12** virtualenv at the repo root: `.venv/`
- Dependencies installed from `hotel_receptionist/requirements.txt`
- Seeded database: `hotel_receptionist/fake_data/hotel.db`
  (regenerate anytime with `python fake_data/seed.py`)
- LiveKit Cloud credentials in `hotel_receptionist/.env.local` (gitignored):
  ```
  LIVEKIT_URL=wss://<your-project>.livekit.cloud
  LIVEKIT_API_KEY=...
  LIVEKIT_API_SECRET=...
  ```
  Get them from https://cloud.livekit.io (**Settings → Keys**), or run
  `lk cloud auth` then `lk app env -w` inside `hotel_receptionist/`.

> These credentials are required even in `console` mode — the `inference.*`
> calls send audio/text to LiveKit's hosted models, which authenticate with them.
> You do **not** need separate Deepgram / Google / Inworld keys.

### Run it — talk in your terminal

```bash
source .venv/bin/activate
cd hotel_receptionist
python agent.py console
```

- macOS will ask for **microphone permission** for your terminal the first time — allow it.
- The agent greets you first, then just speak. `Ctrl+C` to quit.
- Try things like:
  - *"I'd like to book a room for two nights next week."*
  - *"Cancel my reservation — last name Virtanen, code HTL-JX31."*
  - *"There's a Valet charge on HTL-ZP19 I want to dispute."*

### For the browser experience instead

```bash
source .venv/bin/activate
cd hotel_receptionist
python agent.py dev
```

Then open the **[LiveKit Agents Playground](https://agents-playground.livekit.io)**,
select your project, and connect to talk to the agent in the browser.

> Voice works in the playground, but the live-DB visualization from the official
> demo uses a custom frontend, so that panel won't appear here.

### Quick connectivity check (no voice)

```bash
cd hotel_receptionist
set -a; . ./.env.local; set +a
lk room list            # authenticates against your project; empty table = OK
```

---

## Phase 2 — run fully-local (MLX on Apple Silicon)

Runs STT + LLM + TTS on this Mac — **no cloud inference**. (LiveKit Cloud is still used for
room/transport, so you still need the `LIVEKIT_*` credentials from Phase 1.)

| Slot | Local model | How it runs |
|---|---|---|
| VAD | silero | native `livekit-local-inference` (already local) |
| STT | English: Nemotron 3.5 ASR **Streaming** (`nemotron-3.5-asr-streaming-0.6b`) · Mandarin: Qwen3-ASR (`Qwen3-ASR-1.7B-8bit`) | in-process plugins in `local_stt.py` — **no server** |
| LLM | Qwen3-8B (`Qwen3-8B-4bit`) | `mlx_lm.server` on `:8080` |
| TTS | Kokoro (`Kokoro-82M-bf16`) | `mlx-audio` server on `:8000` |

### 1. One-time: install the local extras

```bash
cd hotel_receptionist
VIRTUAL_ENV=../.venv uv pip install -r requirements-local.txt
```

### 2. Enable the local backends

In `hotel_receptionist/.env.local`, alongside the `LIVEKIT_*` credentials:

```
LLM_BACKEND=local
LOCAL_LLM_MODEL=mlx-community/Qwen3-8B-4bit
LOCAL_LLM_BASE_URL=http://127.0.0.1:8080/v1

TTS_BACKEND=local
LOCAL_TTS_MODEL=mlx-community/Kokoro-82M-bf16
LOCAL_TTS_BASE_URL=http://127.0.0.1:8000/v1

STT_BACKEND=local
```

The voice, STT model and STT language default from `AGENT_LANGUAGE` (see "Caller language"
below); set `LOCAL_TTS_VOICE` / `LOCAL_STT_MODEL` / `LOCAL_STT_LANGUAGE` only to override them.
Any `LOCAL_STT_MODEL` containing `nemotron` uses the streaming plugin; anything else uses batch
Qwen3-ASR.

> Mix and match: comment out any one block to keep that component on cloud (e.g. drop the
> `STT_BACKEND` block to keep snappier cloud Deepgram STT while LLM + TTS stay local).

### 3. Start the two model servers (each in its own terminal)

```bash
source .venv/bin/activate

# terminal 1 — LLM
python -m mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080 --prompt-cache-bytes 6GB

# terminal 2 — TTS
python -m mlx_audio.server --host 127.0.0.1 --port 8000
```

(STT needs no server — it loads in-process when the call starts; Nemotron is 1.3 GB, downloaded on
first use.)

> **Keep `--prompt-cache-bytes`.** The agent's system prompt + tool schemas are ~16.5k
> tokens, so each cached conversation holds ~2.5 GB of KV cache. `mlx_lm.server` keeps 10 by
> default (~25 GB) and crashed with a Metal out-of-memory error on a 32 GB Mac after a few
> turns. 6 GB keeps two or three conversations warm.

### 4. Run the agent

```bash
source .venv/bin/activate
cd hotel_receptionist
python agent.py console      # or `dev` for the browser playground
```

**What to expect on local:**
- The very first LLM reply after starting `mlx_lm.server` is slow (~1 min measured): it has to
  prefill the ~16.5k-token prompt once. Later turns reuse the prompt cache (~2–8 s). With
  `LLM_BACKEND=local` the agent waits up to 180 s per LLM call instead of LiveKit's 10 s default
  (override with `LOCAL_LLM_TIMEOUT`), so this cold turn completes instead of timing out.
- **English STT streams:** Nemotron transcribes while you talk (interim text every ~320 ms) and
  the final transcript is ready ~40–75 ms after the VAD detects end-of-speech, vs ~0.2–0.7 s for
  batch Qwen3-ASR (and ~0.8–1.3 s while the LLM is busy). Mandarin still uses batch Qwen3-ASR,
  because Nemotron's Mandarin is unusable. Details and benchmarks: GitHub issue #6.
- Turn latency is still dominated by the LLM (≈4–10 s per reply in a real call on an M1 Max).
- Memory: ~5 GB LLM weights + ~1.3 GB STT (Nemotron; ~2 GB for Qwen3-ASR) + <1 GB TTS, plus the
  LLM prompt cache (capped above).

**Revert to cloud:** comment out the `*_BACKEND` lines in `.env.local` and restart the agent.

### Caller language (English / Mandarin / Taiwan Mandarin)

Set `AGENT_LANGUAGE` in `.env.local` to `en` (default), `zh` (mainland Mandarin, Simplified) or
`zh-tw` (Taiwan Mandarin, Traditional; `zh_tw` also works). Each is a profile in
`hotel_receptionist/languages.py`, and it sets the prompt directive plus the local **and** cloud
model defaults:

| | `en` | `zh` | `zh-tw` |
|---|---|---|---|
| Prompt | unchanged upstream English | English + mainland directive (Simplified) | English + Taiwan directive (Traditional, Taiwan terms, "LiveKit 飯店") |
| Local STT | Nemotron 3.5 streaming | Qwen3-ASR (batch) | Qwen3-ASR (batch) |
| Local TTS (Kokoro) | `af_heart` | `zf_xiaobei` | `zf_xiaobei` (Kokoro has no Taiwan voice) |
| Cloud STT | `deepgram/nova-3` | `assemblyai/u3-rt-pro`, `zh` | `deepgram/nova-3`, `zh-TW` (Traditional output) |
| Cloud TTS | `inworld/inworld-tts-2` | `inworld/inworld-tts-2`, voice `Yichen` | `cartesia/sonic-3.6`, default voice (most Taiwanese by ear) |
| Cloud LLM | `google/gemma-4-31b-it` | `google/gemma-4-31b-it` | `google/gemma-4-31b-it` |

The cloud picks come from a LiveKit-Inference-only evaluation (GitHub issue #1). Findings:
- **Only three hosted STT routes accept Mandarin:** Deepgram, AssemblyAI u3-rt-pro, and `auto` (= Cartesia ink-whisper).
- **Only Deepgram outputs Traditional** characters.
- **Several multi-turn cloud LLMs completed a correct Taiwan-Mandarin booking.**

Phone numbers: LiveKit's phone-number task only accepts international format, so the zh / zh-tw
directives tell the model to pass `+886…` / `+86…` (a local `09xx…` number is otherwise rejected).

`zh` / `zh-tw` on the local stack need `misaki[zh]` (in `requirements-local.txt`) for Kokoro. Known
local limit: Qwen3-8B is unreliable in Mandarin; it once invented a confirmation code (#8).

## Web front-end (remote access)

`web/` is a password-protected browser front-end (Next.js, from LiveKit's agent starter) for
calling the agent from anywhere. There are two password-protected demos:
- `https://hotelbooking.wormhole.work`: local models, served from the Mac through a Cloudflare Tunnel (`deploy/demos.sh`).
- `https://hotel-tw.wormhole.work`: cloud, Taiwan Mandarin, fully off the Mac. The web app is a Cloudflare Worker and the agent is hosted on LiveKit Cloud.
- `https://bendon.wormhole.work`: a second app that takes lunchbox / takeout orders by voice for the store you pick (愛比食堂, 大無敵烤肉飯, 裕佳精緻燒臘), with a live order view. See [`bendon_ordering/README.md`](bendon_ordering/README.md).

Code shared by both apps (model backends, language profiles, local MLX STT) lives in `voiceshared/`.
Deploy hosted agents with `deploy/agent_deploy.sh <app>`. Setup, configuration and known limits: [`web/README-hotel.md`](web/README-hotel.md);
plan: GitHub issue #12.
