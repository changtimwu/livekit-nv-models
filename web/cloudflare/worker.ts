// Cloudflare Worker for the cloud Taiwan-Mandarin demo (issue #16). It serves the static UI
// (scripts/build-static.sh -> out-cf/) and replaces the Next.js server parts:
//   middleware.ts           -> page gating below
//   app/api/login/route.ts  -> POST /api/login (rate limit via Cloudflare binding)
//   app/api/token/route.ts  -> POST /api/token (dispatches AGENT_NAME server-side)
// Session cookies are the same format as the Next.js app (lib/auth.ts).
import { AccessToken, RoomAgentDispatch, RoomConfiguration } from 'livekit-server-sdk';
import { SESSION_COOKIE, SESSION_MAX_AGE_S, createSessionValue, isValidSession } from '../lib/auth';

interface Env {
  ASSETS: Fetcher;
  LOGIN_LIMITER: { limit(opts: { key: string }): Promise<{ success: boolean }> };
  LIVEKIT_URL: string;
  LIVEKIT_API_KEY: string;
  LIVEKIT_API_SECRET: string;
  AGENT_NAME: string;
  // Comma-separated store slugs a caller may pick (bendon demo, #22); empty = no store metadata.
  STORES?: string;
  WEB_PASSWORD: string;
  WEB_SESSION_SECRET: string;
}

// Pages and assets reachable without a session (the login page and what it loads).
const PUBLIC = [
  /^\/login(\.html|\.txt)?$/,
  /^\/_next\//,
  /^\/favicon\.ico$/,
  /\.(svg|png|jpg|ico|otf|woff2?)$/,
];

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
  });

function readCookie(req: Request, name: string): string | undefined {
  const header = req.headers.get('Cookie') ?? '';
  for (const part of header.split(';')) {
    const [k, ...v] = part.trim().split('=');
    if (k === name) return v.join('=');
  }
  return undefined;
}

async function sha256(s: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
}

async function passwordMatches(given: string, expected: string): Promise<boolean> {
  // Compare fixed-length digests in constant time.
  const [a, b] = await Promise.all([sha256(given), sha256(expected)]);
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i] ^ b[i];
  return diff === 0;
}

async function login(req: Request, env: Env): Promise<Response> {
  const ip = req.headers.get('cf-connecting-ip') ?? 'unknown';
  const { success } = await env.LOGIN_LIMITER.limit({ key: `login:${ip}` });
  if (!success) return json({ error: 'Too many attempts. Try again later.' }, 429);

  const body = (await req.json().catch(() => ({}))) as { password?: unknown };
  const password = typeof body.password === 'string' ? body.password : '';
  if (!(await passwordMatches(password, env.WEB_PASSWORD))) {
    return json({ error: 'Wrong password.' }, 401);
  }
  const res = json({ ok: true });
  res.headers.append(
    'Set-Cookie',
    `${SESSION_COOKIE}=${await createSessionValue()}; Path=/; Max-Age=${SESSION_MAX_AGE_S}; HttpOnly; Secure; SameSite=Lax`
  );
  return res;
}

// The page sends the picked store as the agent dispatch metadata; accept only allowlisted
// slugs and write the metadata ourselves, so a visitor can't inject arbitrary metadata.
async function requestedStore(req: Request, env: Env): Promise<string | undefined> {
  const allowed = (env.STORES ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (allowed.length === 0) return undefined;
  let slug: unknown;
  try {
    const body = (await req.json()) as { room_config?: unknown };
    const cfg = body.room_config
      ? RoomConfiguration.fromJson(body.room_config as never, { ignoreUnknownFields: true })
      : undefined;
    const md = cfg?.agents?.[0]?.metadata;
    slug = md ? (JSON.parse(md) as { store?: unknown }).store : undefined;
  } catch {
    slug = undefined;
  }
  return typeof slug === 'string' && allowed.includes(slug) ? slug : allowed[0];
}

async function token(req: Request, env: Env): Promise<Response> {
  // One fresh, unguessable room per call; the site's agent is dispatched server-side.
  const roomName = `hotel_${crypto.randomUUID()}`;
  const at = new AccessToken(env.LIVEKIT_API_KEY, env.LIVEKIT_API_SECRET, {
    identity: `guest_${crypto.randomUUID().slice(0, 8)}`,
    name: 'user',
    ttl: '15m',
  });
  at.addGrant({
    room: roomName,
    roomJoin: true,
    canPublish: true,
    canPublishData: true,
    canSubscribe: true,
  });
  const store = await requestedStore(req, env);
  at.roomConfig = new RoomConfiguration({
    agents: [
      new RoomAgentDispatch({
        agentName: env.AGENT_NAME,
        metadata: store ? JSON.stringify({ store }) : '',
      }),
    ],
  });
  return json({
    serverUrl: env.LIVEKIT_URL,
    roomName,
    participantName: 'user',
    participantToken: await at.toJwt(),
  });
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const { pathname } = new URL(req.url);

    if (pathname === '/api/login' && req.method === 'POST') return login(req, env);
    if (PUBLIC.some((re) => re.test(pathname))) return env.ASSETS.fetch(req);

    const authed = await isValidSession(readCookie(req, SESSION_COOKIE));
    if (pathname.startsWith('/api/')) {
      if (!authed) return json({ error: 'unauthorized' }, 401);
      if (pathname === '/api/token' && req.method === 'POST') return token(req, env);
      return json({ error: 'not found' }, 404);
    }
    if (!authed) return Response.redirect(new URL('/login', req.url).toString(), 307);
    return env.ASSETS.fetch(req);
  },
};
