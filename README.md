# livekit-nv-models

Self-hosting experiments for the LiveKit [`hotel_receptionist`](hotel_receptionist/README.md)
voice-agent example, worked through in phases:

1. **Phase 1 — LiveKit Cloud Inference** ✅ (current) — models served through LiveKit's
   hosted gateway (`inference.STT/LLM/TTS/VAD` in `agent.py`).
2. **Phase 2 — local MLX models** on this Apple-Silicon Mac.
3. **Phase 3 — remote NVIDIA GPU** box.

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
