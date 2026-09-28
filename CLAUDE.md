# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

Two layers in one repo:

1. **`hotel_receptionist/`** — a *vendored copy* of the upstream LiveKit
   [`examples/hotel_receptionist`](https://github.com/livekit/agents/tree/main/examples/hotel_receptionist)
   voice agent (a boutique-hotel phone receptionist).
2. **A phased self-hosting experiment** layered on top: run the agent's models on
   LiveKit Cloud (Phase 1), then locally via **MLX** on Apple Silicon (Phase 2, done),
   then on a remote NVIDIA GPU (Phase 3, planned). Progress + gotchas live in
   `README.md` and `phase2-local-mlx.md`.

The environment is macOS/Apple Silicon. There is **no NVIDIA GPU locally**.

## Environment & setup

- Python venv is at the **repo root `.venv/`** and is pinned to **Python 3.12** (the
  system Python 3.14 lacks wheels for some deps — always use `.venv`).
- Two dependency files, both under `hotel_receptionist/`:
  - `requirements.txt` — base agent (LiveKit + silero + turn-detector + apsw).
  - `requirements-local.txt` — Phase 2 MLX extras (`mlx-lm`, `mlx-audio`,
    `livekit-plugins-openai`, and `setuptools<80` because `webrtcvad` imports
    `pkg_resources`).
- `hotel_receptionist/.env.local` holds `LIVEKIT_*` credentials **and** the backend
  toggles. It is **gitignored**, so it is *not* present in fresh git worktrees — copy
  it from the main checkout if a worktree session needs to run the agent.

```bash
# from repo root
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r hotel_receptionist/requirements.txt
VIRTUAL_ENV=.venv uv pip install -r hotel_receptionist/requirements-local.txt   # Phase 2 only
```

## Common commands

Run the agent **from inside `hotel_receptionist/`** — `agent.py` does
`load_dotenv(".env.local")` (CWD-relative) and appends its own dir to `sys.path`.

```bash
source .venv/bin/activate && cd hotel_receptionist

PYTHONPATH=. python fake_data/seed.py     # (re)generate fake_data/hotel.db + sample codes
python agent.py console                   # talk to the agent in the terminal (mic/speakers)
python agent.py dev                       # connect as a worker; drive via LiveKit Playground
python -m livekit.agents download-files   # pre-cache turn-detector / plugin models
```

There is **no pytest suite** and no `agent.py` eval subcommand. Practical validation used
in this repo:

```bash
python -m py_compile agent.py local_stt.py            # syntax
PYTHONPATH=. python -c "import agent"                  # full import smoke test (all modules)
set -a; . ./.env.local; set +a; lk room list          # LiveKit Cloud credential/connectivity check
```

Correctness of agent *behavior* is graded by the eval infrastructure (see "Evals" below),
which is driven by LiveKit's simulation harness, not a local command here.

## Backend-toggle architecture (repo-specific — read this first)

`agent.py` chooses each model via `_build_llm()` / `_build_tts()` / `_build_stt()`, keyed on
env vars (default `cloud`). This is the seam the whole phased plan hangs on — keep the cloud
default intact when editing.

| Slot | `cloud` (default) | `local` (Phase 2, MLX) |
|---|---|---|
| LLM | `inference.LLM("google/gemma-4-31b-it")` | `openai.LLM(base_url=…)` → `mlx_lm.server` on `:8080` |
| TTS | `inference.TTS("inworld/inworld-tts-2")` | `openai.TTS` subclass → `mlx-audio` server on `:8000` (Kokoro) |
| STT | `inference.STT("deepgram/nova-3")` | `local_stt.py`, in-process, **no server**: `MLXNemotronStreamingSTT` (en, streaming) / `MLXQwen3STT` (zh, batch) |
| VAD | `inference.VAD("silero")` — already runs locally (native `livekit-local-inference`) | (unchanged) |

Toggles (set in `.env.local`): `LLM_BACKEND` / `TTS_BACKEND` / `STT_BACKEND` = `cloud|local`,
plus `LOCAL_{LLM,TTS,STT}_MODEL` / `LOCAL_{LLM,TTS}_BASE_URL` / `LOCAL_TTS_VOICE` /
`LOCAL_STT_LANGUAGE` / `LOCAL_LLM_TIMEOUT`. Mix freely (e.g. local LLM+TTS, cloud STT). `.env.example` documents them.

**Caller language:** `AGENT_LANGUAGE=en|zh|zh-tw` (default `en`; `zh_tw` also accepted), resolved by
`current_language()` in `languages.py`. A profile supplies:
- the prompt directive (`zh` = mainland/Simplified, `zh-tw` = Taiwan/Traditional with Taiwan terms)
- local defaults: Kokoro voice, local STT model + language label
- **cloud** defaults (`cloud_{stt,tts,llm}_*`), passed to `inference.STT/TTS/LLM` only when set.
  `en` sets none, so the cloud path stays byte-identical to upstream.

Explicit `LOCAL_TTS_VOICE` / `LOCAL_STT_MODEL` / `LOCAL_STT_LANGUAGE` still override the profile, so
leave them unset in `.env.local` or `zh` gets the English voice (and `en` loses streaming STT).
Cloud picks and their evaluation (LiveKit Inference only) are in GitHub issue #1.
Adding a language = add a `PROFILES` entry.

**Worker env options:**
- `AGENT_NAME` selects explicit dispatch; empty = automatic.
- `AGENT_HTTP_PORT` sets the health port; the prod default 8081 clashes with a second worker.
- `AGENT_IDLE_PROCESSES` sets the number of pre-warmed processes; the prod default is one per CPU core, each loading the whole agent.

`deploy/demos.sh` runs the local web demo (worker `hotel-local`, web :3100, via the tunnel).

The cloud zh-tw demo runs entirely off the Mac:
- the agent `hotel-cloud-zhtw` is **hosted on LiveKit Cloud** (`hotel_receptionist/Dockerfile`, `livekit.toml`, `lk agent deploy`)
- the web app is a **Cloudflare Worker** (`web/cloudflare/worker.ts`, `web/wrangler.jsonc`, static UI from `web/scripts/build-static.sh`)

⚠️ `lk agent create/deploy` defaults to uploading `.env.local` as secrets. Always pass `--secrets-file .env.cloudagent`.
- **The zh-tw prompt works around Cartesia sonic-3.6 quirks by controlling what the model writes:**
  - Arabic "2" is read as 兩, so numbers are written as Chinese characters with 二; 兩 is kept only as a count before a measure word.
  - 菸 is read as "八", so the prompt says to write 煙.
  - Read-backs are spelled one symbol at a time (@ = 小老鼠, . = 點).
  - Check pronunciation by synthesizing and transcribing with Qwen3-ASR: the transcript shows 二 vs 兩 and 八 vs 煙.
- **Phone numbers must be E.164 for LiveKit's `GetPhoneNumberTask`** (`^\+?[1-9]\d{6,14}$`), which
  rejects any local number starting with 0. The zh / zh-tw directives tell the model to pass
  `+86…` / `+886…`.

To run **fully local**, start two servers first (STT loads in-process on first utterance):

```bash
python -m mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080 --prompt-cache-bytes 6GB  # LLM
python -m mlx_audio.server --host 127.0.0.1 --port 8000                     # TTS (Kokoro)
```

**Non-obvious local-model facts (learned the hard way):**
- **Cloud models route through LiveKit's Inference gateway** (`from livekit.agents import inference`),
  authenticated by the `LIVEKIT_*` creds — you do *not* need Deepgram/Google/Inworld keys, and
  these calls need creds even in `console` mode.
- **STT is a custom in-process plugin, not the mlx-audio server.** mlx-audio's HTTP server
  crashes on Qwen3-ASR (`no Stream(gpu,0) in current thread`; MLX streams are thread-local).
  `local_stt.py` loads+runs the model on one dedicated thread to avoid that.
- **Streaming STT = Nemotron 3.5 ASR Streaming, English only** (issue #6 has the full survey +
  benchmarks). Most mlx-audio ASRs' `stream_generate` only streams *output* tokens after
  encoding the whole clip; only `nemotron_asr` and `voxtral_realtime` take audio incrementally
  (`create_streaming_session()` → `feed`/`step`/`close`). Voxtral 4B is the most accurate but runs at
  2.2× real time on an M1 Max while the LLM generates, so it was rejected. Nemotron's Mandarin
  is unusable, so `zh` keeps batch Qwen3-ASR. `MLXNemotronStreamingSTT` segments utterances with
  its own stream of the session VAD (like `StreamAdapter`): feed continuously, emit INTERIM, and
  on VAD end-of-speech `close()` → drain → FINAL → new session. `_drain()` reads session
  internals (`step()` only ingests a new chunk once encoded frames are used up) — pinned to
  mlx-audio 0.5.x.
- **LiveKit's `openai.TTS` uses an SSE transport for non-OpenAI model ids**, but mlx-audio
  returns raw audio bytes — `_build_tts()` wraps it in a subclass that forces the byte-stream
  path. (Internal `AudioChunkedStream`, pinned to `livekit-plugins-openai` 1.6.x.)
- **Cap `mlx_lm.server`'s prompt cache (`--prompt-cache-bytes 6GB`).** The system prompt + tool
  schemas are ~16.5k tokens, so each cached conversation is ~2.5 GB of KV cache; the default keeps
  10 and hit a Metal out-of-memory crash on a 32 GB Mac within a few turns. Relatedly, the first
  reply after a server start takes ~1 min (cold prefill), as does each `AgentTask`'s first turn;
  later turns hit the prompt cache (~2–8 s). LiveKit's default 10 s LLM timeout would abandon that
  cold turn and retry (piling duplicate prefills onto the server), so `_session_conn_options()`
  raises it to `LOCAL_LLM_TIMEOUT` (default 180 s, 1 retry) when `LLM_BACKEND=local`.
- **Kokoro needs `lang_code` on the wire.** mlx-audio defaults it to `"a"` (English G2P) and
  `openai.TTS` can't send extra body fields, so `_build_tts()` adds `lang_code` (the voice id's
  first letter: `af_heart` → `a`, `zf_xiaobei` → `z`) via an httpx transport. Mandarin also needs
  `misaki[zh]`. Kokoro's zh normalizer reads digits (`240美元`) correctly.
- **`load_dotenv(".env.local")` must run before the local imports in `agent.py`**: `persona.py`
  builds `COMMON_INSTRUCTIONS` at import time and reads `AGENT_LANGUAGE` then.
- **Local LLM = Qwen3-8B.** Survey in GitHub issue #8: Gemma 4 E4B, Qwen3-4B-Instruct-2507 and
  Qwen3.5 2B/4B/9B all chat fine but never call the zero-argument routing tools
  (`start_room_booking` → `BookRoomTask`) in the 33-tool / 16.5k-token prompt, and several claim
  bookings that never happened. Qwen3-8B completes a booking in English. It is not reliable in
  Mandarin: it invented a confirmation code once. Swapping the local LLM needs a full multi-turn
  booking check against the DB, not just a single tool-call probe.
- **Thinking is disabled for every local model** via
  `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`. Qwen3 and Gemma 4 think by
  default under `mlx_lm.server`, and the reply lands in a separate `reasoning` field.
- **Qwen3.5 templates reject non-leading system messages**, which LiveKit inserts at handoffs.
  `_single_system_client()` rewrites them in place as labeled user notes. Merging them into the
  first system message would change the prompt prefix and defeat the prompt cache.
- ⚠️ The root-level `*_hosting_hotel_receptionist_example_locally.md` is an old Copilot export with
  **hallucinated** advice (e.g. a fake `simplismart` TTS plugin). Do not trust it; ground model
  work in real docs / installed code. (Nemotron streaming ASR itself is real and now used, via
  mlx-audio's `nemotron_asr` — not the way that export describes.)

## Agent architecture (the `hotel_receptionist/` example)

- **`HotelReceptionistAgent`** (`agent.py`) = `Agent` + three tool mixins:
  `RoomToolsMixin` / `RestaurantToolsMixin` / `ServicesToolsMixin` (`tools_*.py`). Each mixin
  exposes `@function_tool()` methods (book/lookup/cancel/dispute/etc.). `lookup_policy` reads
  the markdown in `policies/`.
- **Multi-turn flows are `AgentTask` subclasses**, handed off to for a structured sub-dialog
  with their own tool schema, then returning a typed result:
  `BookRoomTask`, `BookRestaurantTask`, `ModifyBookingTask`, `VerifyBookingTask` (verify
  last-name + confirmation code), `GetCardTask`. `context.speech_only()` strips tool mechanics
  from the chat context before handing it to a sub-task (smaller models otherwise imitate tools
  they don't have).
- **`Userdata`** (`common.py`) is the shared session state: the `HotelDB` plus dedup guards
  keyed on *caller-turn counts* — they detect a model silently re-running a booking/cancel flow
  with no new caller input (which would double-book / re-cancel).
- **`hotel_db.py`** = an `apsw` SQLite DB with schema, views, `PRICING`, and dispute policy.
  **Invariant: the LLM never owns money.** `book_room` computes totals server-side
  (`nightly_rate × nights + extras + tax`); `file_dispute` reads the amount from the stored
  invoice line item and clamps any refund to ≤ that amount. Preserve this when editing tools.
- **`ui_view.py`** streams SQLite changesets (via `apsw.Session`) to the playground so the DB
  state renders live — the "wow" of the demo.
- **Prompts:** `instructions.py` (`build_instructions()`) + `persona.py` (`COMMON_INSTRUCTIONS`);
  both stay English for every language. A non-English `AGENT_LANGUAGE` appends its directive from
  `languages.py` to `COMMON_INSTRUCTIONS`, which the main agent and every `AgentTask` embed, so it
  reaches all sub-dialogs. With `en` the prompt is byte-identical to upstream; keep it that way.
- **Evals:** `on_session_end` / `on_simulation_end` in `agent.py` grade a run with a
  `JudgeGroup` (LLM judges) **and** a DB-state diff. `benchmark.py` builds a scenario's
  `expected_state` on a fresh seed and diffs it against the agent's DB (tau-bench style, a
  denylist of columns). `scenarios.yaml` holds the scenarios; `run_artifacts.py` dumps
  per-run artifacts when `LIVEKIT_SESSION_REPORT_DIR` is set.

## Docs

- `README.md` — Phase 1 (cloud) and Phase 2 (fully-local MLX) run/validate instructions.
- `phase2-local-mlx.md` — verified integration details, model IDs, and every gotcha above,
  with a changelog of what was done.
