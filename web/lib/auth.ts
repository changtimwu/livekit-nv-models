// Shared-password session for the hotel demo. The cookie value is
// `<expiry-unix-seconds>.<HMAC-SHA256(expiry)>`, signed with WEB_SESSION_SECRET.
// Web Crypto only, so it works in both middleware (edge) and route handlers.

export const SESSION_COOKIE = 'hotel_session';
export const SESSION_MAX_AGE_S = 7 * 24 * 60 * 60;

const encoder = new TextEncoder();

function sessionSecret(): string {
  const secret = process.env.WEB_SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error('WEB_SESSION_SECRET must be set (at least 32 characters)');
  }
  return secret;
}

function toBase64Url(buf: ArrayBuffer): string {
  let bin = '';
  for (const b of new Uint8Array(buf)) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function sign(data: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(sessionSecret()),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  return toBase64Url(await crypto.subtle.sign('HMAC', key, encoder.encode(data)));
}

function constantTimeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function createSessionValue(): Promise<string> {
  const expiry = Math.floor(Date.now() / 1000) + SESSION_MAX_AGE_S;
  return `${expiry}.${await sign(String(expiry))}`;
}

export async function isValidSession(value: string | undefined): Promise<boolean> {
  if (!value) return false;
  const [expiry, signature] = value.split('.');
  if (!expiry || !signature || !/^\d+$/.test(expiry)) return false;
  if (Number(expiry) < Date.now() / 1000) return false;
  return constantTimeEqual(signature, await sign(expiry));
}
