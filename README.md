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
| STT | Qwen3-ASR (`Qwen3-ASR-1.7B-8bit`) | in-process plugin `local_stt.py` — **no server** |
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
LOCAL_STT_MODEL=mlx-community/Qwen3-ASR-1.7B-8bit
```

The voice and STT language default from `AGENT_LANGUAGE` (see "Caller language" below);
set `LOCAL_TTS_VOICE` / `LOCAL_STT_LANGUAGE` only to override them.

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

(STT needs no server — it loads in-process on the first utterance.)

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
- First utterance has a ~1–2 s pause while Qwen3-ASR loads into memory.
- The very first LLM reply after starting `mlx_lm.server` is slow (~1 min measured): it has to
  prefill the ~16.5k-token prompt once. Later turns reuse the prompt cache (~2–8 s). With
  `LLM_BACKEND=local` the agent waits up to 180 s per LLM call instead of LiveKit's 10 s default
  (override with `LOCAL_LLM_TIMEOUT`), so this cold turn completes instead of timing out.
- Local STT is batch (VAD-gated), so replies begin *after* you finish speaking, not mid-sentence.
- Memory: ~5 GB LLM weights + ~2 GB STT + <1 GB TTS, plus the LLM prompt cache (capped above).

**Revert to cloud:** comment out the `*_BACKEND` lines in `.env.local` and restart the agent.

### Caller language (English / Mandarin)

Set `AGENT_LANGUAGE` in `.env.local` to `en` (default) or `zh`:

| | `en` | `zh` |
|---|---|---|
| Prompt | unchanged upstream English prompt | same English prompt + a Mandarin directive (`hotel_receptionist/languages.py`) |
| Kokoro voice | `af_heart` | `zf_xiaobei` (also `zf_xiaoni`, `zf_xiaoxiao`, `zf_xiaoyi`, `zm_yunjian`, `zm_yunxi`, `zm_yunxia`, `zm_yunyang`) |
| STT | Qwen3-ASR (auto-detects; label `en`) | Qwen3-ASR (auto-detects; label `zh`) |

`zh` needs `misaki[zh]` (in `requirements-local.txt`) for Kokoro's Mandarin G2P, and is tuned
for the **local** backends only — with any cloud backend the agent logs a warning, since
cloud-stack Mandarin support is still open (GitHub issue #1). Known limit: Qwen3-8B follows
the Mandarin directive well but, as in English, sometimes lists every option and price at
once instead of narrowing progressively.
