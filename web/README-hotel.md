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

## Two public demos (`deploy/demos.sh start|stop|status`)

| URL | web port | agent worker (`AGENT_NAME`) | stack |
|---|---|---|---|
| https://hotelbooking.wormhole.work | 3100 | `hotel-local` | local MLX models, language from `hotel_receptionist/.env.local` |
| https://hotel-tw.wormhole.work | 3101 | `hotel-cloud-zhtw` | LiveKit Inference, `AGENT_LANGUAGE=zh-tw` (Deepgram → Gemma 4 31B → Cartesia) |

- **Separate named workers.** Both workers share one LiveKit project, so each has an `AGENT_NAME` and each site dispatches its own. With automatic dispatch, calls would land on either worker at random.
- **Worker settings.** The cloud worker gets its settings from env vars (they take precedence over `.env.local`) and a second health port (`AGENT_HTTP_PORT=8082`). Both run with `AGENT_IDLE_PROCESSES=1`, instead of one pre-warmed process per CPU core.
- **Password.** Both sites use the same password (`WEB_PASSWORD` in `web/.env.local`).
- **Cost.** Cloud-demo calls are billed to the LiveKit plan.
- **Routing.** Cloudflare Tunnel `mymbpr` maps the hostnames to the ports (`cf-publish` skill: `add-route.sh <sub> <port>`). The tunnel needs the cloudflared system service running.
- **Local demo dependencies.** It also needs `mlx_lm.server` (:8080) and `mlx_audio.server` (:8000).
- **Stopping.** Next.js renames its process to `next-server`, so `demos.sh stop` stops web servers by port.

## Known limits (see issue #12, #11)

- **No call cap yet.** Two visitors at once would share the one local GPU. Planned: a concurrency cap and a "busy" message.
- **Slow cold start.** The first reply after the LLM's prompt cache goes cold can take ~1 min (#11).
- The caller language follows `AGENT_LANGUAGE` in `hotel_receptionist/.env.local`.
