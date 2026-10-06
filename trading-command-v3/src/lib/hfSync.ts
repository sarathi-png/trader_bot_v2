/**
 * Optional Hugging Face Dataset mirror.
 *
 * Port of `sync_to_dataset` in trader_bot_v2/storage.py: when the Space/host
 * runs on ephemeral disk, pushing the JSON documents to a (free) Dataset repo
 * after a write keeps history alive across restarts.
 *
 * Behaviour — deliberately ALL of this:
 *   - no-op unless BOTH HF_DATASET_ID and HF_TOKEN are set
 *   - never throws into a request path: every failure is swallowed and logged
 *   - never blocks a response: callers get a resolved promise immediately
 *   - rate limited to one attempt per HF_SYNC_INTERVAL_MS (default 300s), so a
 *     busy dashboard cannot hammer the API
 */
import { readDocUncached } from "@/lib/fileStore";
import { ALL_DOCS } from "@/lib/repo/file";

/** Directory the documents are mirrored into inside the Dataset repo. */
const REPO_PREFIX = "trading-command-v3";

function intervalMs(): number {
  const raw = Number(process.env.HF_SYNC_INTERVAL_MS ?? 300_000);
  return Number.isFinite(raw) && raw >= 0 ? raw : 300_000;
}

export function hfSyncConfigured(): boolean {
  return Boolean(process.env.HF_DATASET_ID && process.env.HF_TOKEN);
}

let inFlight = false;
let lastAttemptAt = 0;

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(resolve, ms);
    // Do not hold the process open just for a background mirror.
    (t as unknown as { unref?: () => void }).unref?.();
  });
}

async function upload(doc: string, body: string): Promise<boolean> {
  const repo = process.env.HF_DATASET_ID as string;
  const token = process.env.HF_TOKEN as string;
  const base = process.env.HF_API_BASE || "https://huggingface.co";
  const path = `${REPO_PREFIX}/${doc}`;
  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/octet-stream",
  };
  const endpoints = [
    // Files API (commit-style) — preferred, returns JSON.
    `${base}/api/datasets/${repo}/paths/main/${path}?commit_message=${encodeURIComponent(
      `trading-command sync ${doc}`
    )}`,
    // Legacy upload endpoint.
    `${base}/api/datasets/${repo}/upload/main/${path}`,
  ];
  for (const url of endpoints) {
    try {
      const res = await fetch(url, { method: "POST", headers, body });
      if (res.ok) return true;
      // 4xx (other than rate limiting) will not improve on the next endpoint.
      if (res.status >= 400 && res.status < 500 && res.status !== 429) return false;
    } catch {
      // try the next endpoint
    }
  }
  return false;
}

async function syncNow(): Promise<void> {
  for (const doc of ALL_DOCS) {
    const value = readDocUncached<unknown>(doc, null);
    if (value === null) continue; // never uploaded yet
    await upload(doc, JSON.stringify(value, null, 2));
  }
}

/**
 * Request a mirror of the data directory. Returns immediately; the work happens
 * in the background and is bounded by the throttle window. Safe to call after
 * every write.
 */
export function scheduleHfSync(): void {
  if (!hfSyncConfigured()) return;
  const now = Date.now();
  if (inFlight) return;
  if (now - lastAttemptAt < intervalMs()) return;
  lastAttemptAt = now;
  inFlight = true;
  void (async () => {
    try {
      await syncNow();
    } catch {
      /* a mirror failure must never surface anywhere */
    } finally {
      inFlight = false;
      // Yield so a burst of writes cannot stack up timers.
      await sleep(0);
    }
  })().catch(() => undefined);
}
