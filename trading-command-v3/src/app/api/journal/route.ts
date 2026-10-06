import { getRepo } from "@/lib/repo";
import type { JournalInsert, JournalRow } from "@/lib/repo";
import { getSettings, logAudit, updateSettings } from "@/lib/settings";
import { DEMO_SYMBOLS } from "@/lib/market/demo";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

function parseNum(v: unknown, fallback = 0): number {
  const n = typeof v === "string" ? parseFloat(v) : typeof v === "number" ? v : NaN;
  return Number.isFinite(n) ? n : fallback;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const symbol = url.searchParams.get("symbol");
  const mode = url.searchParams.get("mode");
  const rows = await (await getRepo()).listJournal({
    symbol: symbol?.toUpperCase(),
    mode: mode ?? undefined,
    limit: 800,
  });
  return Response.json({ entries: rows });
}

async function seedDemoJournal(): Promise<number> {
  const strategies = ["trend", "breakout", "sr", "manual"];
  const emotions = ["calm", "calm", "focused", "hesitant", "rushed", "disciplined", ""];
  const now = Date.now();
  const count = 26;
  const values: JournalInsert[] = [];
  let seedState = 1234567;
  const rng = () => {
    seedState = (seedState * 1103515245 + 12345) % 2147483648;
    return seedState / 2147483648;
  };
  for (let i = 0; i < count; i++) {
    const sym = DEMO_SYMBOLS[Math.floor(rng() * 3)].symbol;
    const base = DEMO_SYMBOLS.find((s) => s.symbol === sym)?.base ?? 100;
    const direction = rng() > 0.48 ? "long" : "short";
    const win = rng() < 0.55;
    const pnl = win ? 18 + rng() * 120 : -(12 + rng() * 65);
    const entry = base * (0.93 + rng() * 0.12);
    const qty = Math.max(0.001, (40 + rng() * 60) / entry);
    const dirMul = direction === "long" ? 1 : -1;
    const exit = entry + (pnl / qty) * dirMul;
    const openedAt = new Date(now - (i + 1) * (0.6 + rng() * 1.4) * 86400000);
    const durMs = (20 + rng() * 460) * 60000;
    values.push({
      mode: "demo" as const,
      symbol: sym,
      direction,
      entry,
      exit,
      qty,
      fees: Math.abs(qty * entry * 0.001),
      pnl,
      strategy: strategies[Math.floor(rng() * strategies.length)],
      reason: win ? "Setup followed as planned" : "Entry taken ahead of confirmation",
      notes: "",
      emotion: emotions[Math.floor(rng() * emotions.length)],
      tags: ["sample"],
      openedAt,
      closedAt: new Date(openedAt.getTime() + durMs),
      source: "seed" as const,
    });
  }
  const inserted = await (await getRepo()).insertJournalMany(values);
  return inserted;
}

export async function POST(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  if (body.action === "seed") {
    const settings = await getSettings();
    if (settings.seededDemo) {
      return Response.json({ error: "Sample data already loaded" }, { status: 400 });
    }
    const n = await seedDemoJournal();
    await updateSettings({ seededDemo: true });
    await logAudit("demo_journal_seeded", { trades: n });
    return Response.json({ ok: true, seeded: n });
  }

  const symbol = String(body.symbol ?? "").toUpperCase().trim();
  if (!symbol) return Response.json({ error: "Symbol is required" }, { status: 400 });
  const direction = body.direction === "short" ? "short" : "long";
  const entry = parseNum(body.entry);
  const qty = parseNum(body.qty);
  if (entry <= 0 || qty <= 0) {
    return Response.json({ error: "Entry price and quantity must be positive" }, { status: 400 });
  }
  const exit = body.exit === null || body.exit === undefined ? null : parseNum(body.exit);
  const pnl = parseNum(body.pnl);
  const row = await (await getRepo()).insertJournal({
    mode: "live",
    symbol,
    direction,
    entry,
    exit,
    qty,
    fees: parseNum(body.fees),
    pnl,
    strategy: String(body.strategy ?? ""),
    reason: String(body.reason ?? ""),
    notes: String(body.notes ?? ""),
    emotion: String(body.emotion ?? ""),
    tags: Array.isArray(body.tags) ? body.tags.map(String) : [],
    openedAt: body.openedAt ? new Date(String(body.openedAt)) : new Date(),
    closedAt: exit !== null ? new Date() : null,
    source: "manual",
  });
  await logAudit("journal_entry_created", { symbol, direction });
  return Response.json({ entry: row });
}

export async function PATCH(req: Request) {
  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const id = String(body.id ?? "");
  if (!id) return Response.json({ error: "id required" }, { status: 400 });
  const patch: Partial<JournalRow> = {};
  for (const k of ["strategy", "reason", "notes", "emotion"] as const) {
    if (typeof body[k] === "string") patch[k] = body[k];
  }
  if (Array.isArray(body.tags)) patch.tags = body.tags.map(String);
  for (const k of ["entry", "exit", "qty", "fees", "pnl"] as const) {
    if (typeof body[k] === "number") patch[k] = body[k];
  }
  const row = await (await getRepo()).updateJournal(id, patch);
  if (!row) return Response.json({ error: "Entry not found" }, { status: 404 });
  return Response.json({ entry: row });
}

export async function DELETE(req: Request) {
  const id = new URL(req.url).searchParams.get("id");
  if (!id) return Response.json({ error: "id required" }, { status: 400 });
  await (await getRepo()).deleteJournal(id);
  return Response.json({ ok: true });
}
