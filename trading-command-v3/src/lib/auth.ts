/**
 * Authentication for the dashboard API.
 *
 * These routes can move real money, so every caller must prove they are the
 * operator before anything else happens. Two credentials are accepted:
 *
 *   - a signed session cookie issued by POST /api/auth/login (browser use)
 *   - `Authorization: Bearer <API_PASSWORD>` (scripts, curl, smoke tests)
 *
 * FAIL CLOSED. If API_PASSWORD is unset, authentication is *unconfigured* and
 * every protected route is refused. A missing env var must never be read as
 * "open", otherwise a half-configured deployment silently exposes order
 * placement to the internet.
 *
 * Only Web Crypto is used (no node:crypto) so this module is safe to import
 * from Edge middleware as well as Node route handlers.
 */
import type { NextRequest } from "next/server";

const enc = new TextEncoder();

/** Cookie carrying the signed session. */
export const SESSION_COOKIE = "tc_session";

/** Sessions last 12 hours; re-login after that. */
export const SESSION_TTL_MS = 12 * 60 * 60 * 1000;

/**
 * Constant-time string comparison.
 *
 * Plain `===` leaks the length of the matching prefix through timing, which is
 * enough to brute-force a shared secret one character at a time.
 */
export function timingSafeEqual(a: string, b: string): boolean {
  const ab = enc.encode(a);
  const bb = enc.encode(b);
  const len = Math.max(ab.length, bb.length);
  let diff = ab.length ^ bb.length;
  for (let i = 0; i < len; i++) diff |= (ab[i] ?? 0) ^ (bb[i] ?? 0);
  return diff === 0;
}

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function fromHex(hex: string): Uint8Array {
  if (hex.length % 2 !== 0) return new Uint8Array();
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  return out;
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"]
  );
}

/** The operator password, or "" when unconfigured. */
export function apiPassword(): string {
  return process.env.API_PASSWORD ?? "";
}

/** Secret used to sign session cookies. Falls back to the password. */
export function sessionSecret(): string {
  return process.env.SESSION_SECRET || apiPassword();
}

/** True when the deployment has a password to authenticate against. */
export function authConfigured(): boolean {
  return apiPassword().length > 0;
}

/** Constant-time check of a caller-supplied password. */
export function passwordMatches(provided: string | null | undefined): boolean {
  const expected = apiPassword();
  if (!expected || !provided) return false;
  return timingSafeEqual(provided, expected);
}

/** Extract a bearer token from an Authorization header, if present. */
export function bearerFrom(header: string | null): string | null {
  if (!header) return null;
  const match = /^Bearer\s+(.+)$/i.exec(header.trim());
  return match ? match[1].trim() : null;
}

/** Sign a session token carrying only an expiry, bound to the secret. */
export async function signSession(expiresAt: number, secret: string): Promise<string> {
  const payload = `v1.${expiresAt}`;
  const key = await hmacKey(secret);
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(payload));
  return `${payload}.${toHex(new Uint8Array(sig))}`;
}

/** Verify signature and expiry. Rejects tampered, malformed or stale tokens. */
export async function verifySession(
  token: string | null | undefined,
  secret: string,
  now: number = Date.now()
): Promise<boolean> {
  if (!token || !secret) return false;
  const parts = token.split(".");
  if (parts.length !== 3) return false;
  const [version, exp, sig] = parts;
  if (version !== "v1") return false;
  const expiresAt = Number(exp);
  if (!Number.isFinite(expiresAt) || expiresAt <= now) return false;
  const key = await hmacKey(secret);
  try {
    return await crypto.subtle.verify(
      "HMAC",
      key,
      fromHex(sig) as unknown as ArrayBuffer,
      enc.encode(`v1.${expiresAt}`) as unknown as ArrayBuffer
    );
  } catch {
    return false;
  }
}

/** True when the request carries a valid bearer token or session cookie. */
export async function isAuthenticated(req: NextRequest): Promise<boolean> {
  if (!authConfigured()) return false;
  const bearer = bearerFrom(req.headers.get("authorization"));
  if (bearer && passwordMatches(bearer)) return true;
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  return verifySession(token, sessionSecret());
}