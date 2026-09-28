# Hotel receptionist web front-end

Browser front-end for the local hotel receptionist agent, based on
[`livekit-examples/agent-starter-react`](https://github.com/livekit-examples/agent-starter-react)
(the upstream `README.md` still applies for general usage). Plan and decisions: GitHub issue #12.

The browser talks to LiveKit Cloud; the agent worker on the Mac connects to LiveKit Cloud
outbound. This app only serves the page and mints room tokens, so it is the only thing exposed.

## What was changed from the starter

- **Shared-password lock.** `/login` posts to `/api/login`, which checks `WEB_PASSWORD`
  (constant-time; 10 attempts / 15 min per IP) and sets a signed, httpOnly session cookie
  (`lib/auth.ts`, 7 days). `middleware.ts` gates every page and API route.
- **Token route** (`app/api/token/route.ts`) re-checks the session. Without it, anyone could
  start a call on the Mac. It mints a 15-minute token for a fresh, unguessable room; the hotel
  agent is auto-dispatched into it (leave `AGENT_NAME` empty).
- Hotel branding, video input off.
- **Named dispatch:** when `AGENT_NAME` is set, the token route adds it to the room
  configuration server-side, so a visitor can't pick a different worker. `/` renders per
  request, so one build serves several instances with different `AGENT_NAME` / `SITE_TAGLINE`.

## Configure (`web/.env.local`, gitignored)

```
LIVEKIT_URL=wss://<project>.livekit.cloud     # same values as hotel_receptionist/.env.local
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
AGENT_NAME=                                   # empty = automatic dispatch; set per instance below
SITE_TAGLINE=                                 # optional line under the title
WEB_PASSWORD=<shared password>                # change + restart to rotate
WEB_SESSION_SECRET=<48+ random chars>         # changing it logs everyone out
```

## Run

```bash
npx pnpm@9.15.9 install        # Node 25+ no longer ships corepack, so run pnpm via npx
npx pnpm@9.15.9 build
npx pnpm@9.15.9 start -p 3100
```

Also needed on the Mac:
- the model servers (see the repo README)
- the agent worker in production mode: `cd hotel_receptionist && python agent.py start`

## Two public demos

| URL | web | agent | stack |
|---|---|---|---|
| https://hotelbooking.wormhole.work | Next.js on the Mac (:3100) via Cloudflare Tunnel `mymbpr` | `hotel-local` on the Mac | local MLX models (`hotel_receptionist/.env.local`) |
| https://hotel-tw.wormhole.work | **Cloudflare Worker** `hotel-tw-demo` (static UI + login/token) | `hotel-cloud-zhtw` **hosted on LiveKit Cloud** (`CA_fabSGTJxjW3r`, us-east) | LiveKit Inference, `zh-tw` |

The cloud demo needs nothing on the Mac (issue #16). Both sites use the same password.

### Local demo (Mac): `deploy/demos.sh start|stop|status`
- **Worker:** runs `hotel-local` with `AGENT_IDLE_PROCESSES=1` (instead of one pre-warmed process per CPU core).
- **Model servers:** needs `mlx_lm.server` (:8080) and `mlx_audio.server` (:8000).
- **Stopping:** `stop` kills the web server by port, because Next.js renames its process to `next-server`.

### Cloud demo: agent (LiveKit Cloud)
```bash
cd hotel_receptionist
lk agent deploy                                    # rebuild + roll out from livekit.toml
lk agent logs                                      # runtime logs
lk agent update-secrets --secrets-file .env.cloudagent
```
- **Image:** `Dockerfile` installs only base `requirements.txt`, pinned by `constraints-cloud.txt`.
- **Secrets:** `.env.cloudagent` (gitignored) sets `AGENT_NAME`, `AGENT_LANGUAGE=zh-tw` and cloud backends.
- ⚠️ **Always pass `--secrets-file .env.cloudagent`.** `lk agent create` otherwise uploads `.env.local`, which contains the local-backend settings and the LiveKit credentials.

### Cloud demo: web (Cloudflare Worker)
```bash
cd web
SITE_TAGLINE="台灣華語 · 雲端模型 (LiveKit Inference)" scripts/build-static.sh   # -> out-cf/
npx wrangler deploy                                # wrangler.jsonc; custom domain hotel-tw.wormhole.work
```
- **Static UI:** `scripts/build-static.sh` builds the same UI as a static export, from a temporary copy without `app/api` / `middleware.ts`.
- **Worker:** `cloudflare/worker.ts` serves it with `run_worker_first` and reimplements page gating, `/api/login` and `/api/token` (dispatching `hotel-cloud-zhtw` server-side), reusing `lib/auth.ts`.
- **Secrets:** set once with `wrangler secret put` (or `secret bulk`): `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `WEB_PASSWORD`, `WEB_SESSION_SECRET`.
- **Login rate limit:** Cloudflare's binding, 10 per 60 s per IP. It's approximate and per location; in testing it kicked in around the 27th rapid attempt.

## Known limits (see issue #12, #11)

- **No call cap yet on the local demo.** Two visitors at once would share the one local GPU. Planned: a concurrency cap and a "busy" message. (The cloud demo scales on LiveKit Cloud: 20 concurrent sessions on Ship.)
- **Slow cold start.** The first reply after the LLM's prompt cache goes cold can take ~1 min (#11).
- The caller language follows `AGENT_LANGUAGE` in `hotel_receptionist/.env.local`.
