/**
 * Server-side storage for exchange credentials.
 *
 * The original design read keys only from the environment, which left nowhere
 * in the UI to enter them. This adds an encrypted-at-rest path so the operator
 * can paste Delta keys from the dashboard without editing .env and restarting.
 *
 * Invariants this module exists to enforce:
 *   - plaintext exists only in server memory, never in a response body
 *   - the encryption key is derived from SESSION_SECRET, so a stolen database
 *     dump is useless on its own
 *   - environment variables still win, so a deployment that already supplies
 *     keys is unaffected
 *   - stored rows carry no plaintext to grep for
 *
 * Stored under the existing settings table, so this needs no migration.
 */
import crypto from "node:crypto";
import { getRepo } from "@/lib/repo";

const CREDENTIALS_KEY = "credentials.delta";
const SCHEMA_VERSION = 1;
const CACHE_MS = 30_000;

interface StoredEnvelope {
  v: number;
  apiKey: string; // "v1:<iv>:<ciphertext>:<tag>"
  apiSecret: string;
  updatedAt: string;
}

let cache: { at: number; value: { apiKey: string; apiSecret: string } | null } | null = null;

function encryptionKey(): Buffer {
  const secret = process.env.SESSION_SECRET || process.env.API_PASSWORD || "";
  if (!secret) {
    throw new Error(
      "SESSION_SECRET or API_PASSWORD must be set before exchange credentials can be stored."
    );
  }
  // A fixed salt is acceptable here: the key material is a high-entropy secret,
  // not a user password, and the goal is a stable key across restarts.
  return crypto.createHash("sha256").update(`delta-credentials:${secret}`).digest();
}

function encrypt(plaintext: string): string {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", encryptionKey(), iv);
  const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
  const tag = cipher.getAuthTag();
  return `v1:${iv.toString("base64")}:${ciphertext.toString("base64")}:${tag.toString("base64")}`;
}

function decrypt(envelope: string): string | null {
  const parts = envelope.split(":");
  if (parts.length !== 4 || parts[0] !== "v1") return null;
  try {
    const [, iv, ciphertext, tag] = parts;
    const decipher = crypto.createDecipheriv(
      "aes-256-gcm",
      encryptionKey(),
      Buffer.from(iv, "base64")
    );
    decipher.setAuthTag(Buffer.from(tag, "base64"));
    return Buffer.concat([
      decipher.update(Buffer.from(ciphertext, "base64")),
      decipher.final(),
    ]).toString("utf8");
  } catch {
    // Wrong SESSION_SECRET or tampered ciphertext. Never fall back to a guess.
    return null;
  }
}

function envCredentials(): { apiKey: string; apiSecret: string } | null {
  const apiKey = process.env.DELTA_API_KEY;
  const apiSecret = process.env.DELTA_API_SECRET;
  if (apiKey && apiSecret) return { apiKey, apiSecret };
  return null;
}

async function readStored(): Promise<StoredEnvelope | null> {
  const value = (await (await getRepo()).getSetting(CREDENTIALS_KEY)) as StoredEnvelope | null;
  return value ?? null;
}

/** Resolve usable credentials: environment first, then the encrypted row. */
export async function resolveDeltaCredentials(): Promise<{
  apiKey: string;
  apiSecret: string;
  source: "env" | "stored";
} | null> {
  const fromEnv = envCredentials();
  if (fromEnv) return { ...fromEnv, source: "env" };

  if (cache && Date.now() - cache.at < CACHE_MS) {
    return cache.value ? { ...cache.value, source: "stored" } : null;
  }

  let value: { apiKey: string; apiSecret: string } | null = null;
  try {
    const row = await readStored();
    if (row?.v === SCHEMA_VERSION) {
      const apiKey = decrypt(row.apiKey);
      const apiSecret = decrypt(row.apiSecret);
      if (apiKey && apiSecret) value = { apiKey, apiSecret };
    }
  } catch {
    value = null; // database unavailable -> behave as unconfigured
  }
  cache = { at: Date.now(), value };
  return value ? { ...value, source: "stored" } : null;
}

/** True when private Delta endpoints can be called. Safe to call per request. */
export async function deltaAccountConfigured(): Promise<boolean> {
  return (await resolveDeltaCredentials()) !== null;
}

/**
 * Status for the UI. Deliberately reveals nothing beyond whether credentials
 * exist and where they came from — no masked key, no length, no fingerprint.
 */
export async function deltaCredentialsStatus(): Promise<{
  configured: boolean;
  source: "env" | "stored" | "none";
}> {
  const resolved = await resolveDeltaCredentials();
  return { configured: resolved !== null, source: resolved?.source ?? "none" };
}

export async function saveDeltaCredentials(
  apiKey: string,
  apiSecret: string
): Promise<void> {
  const envelope: StoredEnvelope = {
    v: SCHEMA_VERSION,
    apiKey: encrypt(apiKey),
    apiSecret: encrypt(apiSecret),
    updatedAt: new Date().toISOString(),
  };
  await (await getRepo()).saveSetting(CREDENTIALS_KEY, envelope);
  cache = null; // pick up immediately rather than waiting for the TTL
}

export async function clearDeltaCredentials(): Promise<void> {
  await (await getRepo()).deleteSetting(CREDENTIALS_KEY);
  cache = null;
}