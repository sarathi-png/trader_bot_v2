/**
 * File-backed JSON document store.
 *
 * The terminal must be fully usable on a workstation with no PostgreSQL. This
 * module is the storage primitive behind the `file` repository backend: each
 * logical table is one JSON document under `data/`.
 *
 * Guarantees:
 *   - the directory is created lazily; a missing directory is never an error
 *   - writes are atomic (write to `<name>.tmp`, then rename over the target) so
 *     a crash mid-write cannot leave a truncated document behind
 *   - reads are cached in-process for a short TTL so a single request that
 *     touches the same document several times hits the disk once; writes
 *     invalidate the cache immediately so read-after-write is always correct
 *   - nothing here throws for I/O reasons: a corrupt or unreadable document
 *     degrades to the caller's fallback value rather than breaking a request
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

let ROOT = process.env.TC_DATA_DIR
  ? path.resolve(process.env.TC_DATA_DIR)
  : path.join(process.cwd(), "data");

/** Cache lifetime for parsed documents. Writes always refresh their own entry. */
const CACHE_MS = Number(process.env.FILE_STORE_CACHE_MS ?? 1000) || 1000;

type CacheEntry = { at: number; value: unknown };
const cache = new Map<string, CacheEntry>();
/** Per-document write queue, so concurrent requests cannot interleave writes. */
const writeQueue = new Map<string, Promise<unknown>>();

type WriteHook = (doc: string) => void;
let writeHook: WriteHook | null = null;

/**
 * Registered by the repository layer: called after a document is durably
 * written, used to schedule the best-effort Hugging Face mirror. Intentionally
 * an indirection so this module stays free of networking code.
 */
export function onAfterWrite(hook: WriteHook | null): void {
  writeHook = hook;
}

export function dataDir(): string {
  return ROOT;
}

function filePath(name: string): string {
  // Names are internal constants ("settings.json"), but normalise anyway so a
  // bad name can never escape the data directory.
  const safe = path.basename(name).replace(/[^\w.\-]/g, "_");
  return path.join(ROOT, safe.endsWith(".json") ? safe : `${safe}.json`);
}

function ensureDir(): boolean {
  try {
    fs.mkdirSync(ROOT, { recursive: true });
    return true;
  } catch {
    // Serverless hosts (Vercel, Netlify) mount the deployment directory
    // READ-ONLY; only /tmp is writable there. Fall back once so the store
    // keeps serving for the lifetime of the instance instead of failing
    // every request. An explicit TC_DATA_DIR always wins, no fallback.
    if (!process.env.TC_DATA_DIR && !ROOT.startsWith(os.tmpdir())) {
      try {
        ROOT = path.join(os.tmpdir(), "trading-command-v3-data");
        cache.clear();
        fs.mkdirSync(ROOT, { recursive: true });
        return true;
      } catch {
        return false;
      }
    }
    return false;
  }
}

/** Drop the cached parse of a document (after an external change, or a write). */
export function invalidateDoc(name: string): void {
  cache.delete(name);
}

/** Drop every cached document — used by tests and after out-of-band writes. */
export function invalidateAll(): void {
  cache.clear();
}

function parseDoc<T>(file: string, fallback: T): T {
  let raw: string;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch {
    // Missing (first run) or unreadable: fall back without failing the request.
    return fallback;
  }
  if (!raw.trim()) return fallback;
  try {
    const parsed = JSON.parse(raw) as T;
    return parsed === null || parsed === undefined ? fallback : parsed;
  } catch {
    // A corrupt document must not take the whole route down. Keep the bad file
    // for forensics under a `.corrupt-<ts>` name and start from the fallback.
    try {
      fs.renameSync(file, `${file}.corrupt-${Date.now()}`);
    } catch {
      /* best effort */
    }
    return fallback;
  }
}

/**
 * Read a JSON document, returning `fallback` when it does not exist yet or
 * cannot be parsed. Repeated reads within the cache window are served from
 * memory.
 */
export function readDoc<T>(name: string, fallback: T): T {
  const hit = cache.get(name);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.value as T;
  const value = parseDoc<T>(filePath(name), fallback);
  cache.set(name, { at: Date.now(), value });
  return value;
}

/** Synchronous peek with no caching — used by the HF mirror snapshot. */
export function readDocUncached<T>(name: string, fallback: T): T {
  return parseDoc<T>(filePath(name), fallback);
}

/**
 * Persist a JSON document atomically. Writes for the same document are
 * serialised, so concurrent requests cannot interleave. Resolves to `false`
 * (never throws) when the data directory is not writable.
 */
export function writeDoc<T>(name: string, value: T): Promise<boolean> {
  const prev = writeQueue.get(name) ?? Promise.resolve();
  const next = prev.then(
    () => commit(name, value),
    () => commit(name, value)
  );
  writeQueue.set(
    name,
    next.catch(() => undefined)
  );
  return next;
}

function commit<T>(name: string, value: T): boolean {
  if (!ensureDir()) return false;
  const target = filePath(name);
  const tmp = `${target}.tmp-${process.pid}-${Math.random().toString(36).slice(2, 8)}`;
  try {
    fs.writeFileSync(tmp, `${JSON.stringify(value, null, 2)}\n`, "utf8");
    fs.renameSync(tmp, target); // atomic on the same volume
  } catch {
    try {
      fs.unlinkSync(tmp);
    } catch {
      /* best effort */
    }
    return false;
  }
  cache.set(name, { at: Date.now(), value });
  try {
    writeHook?.(name);
  } catch {
    // A mirror hook must never be able to fail a write.
  }
  return true;
}
