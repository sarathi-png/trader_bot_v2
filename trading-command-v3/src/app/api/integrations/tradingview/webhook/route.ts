/**
 * OPTIONAL TradingView webhook receiver — DISABLED by default.
 *
 * Even when enabled this endpoint NEVER places orders. Incoming alerts are
 * validated, normalized into internal Signal objects and stored for the user
 * (or a future automation rule) to act on.
 */
import { getRepo } from "@/lib/repo";
import type { SignalRow } from "@/lib/repo";
import { flags } from "@/lib/flags";
import { getSettings, logAudit } from "@/lib/settings";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const seen = new Map<string, number>(); // payload hash → ts, dedupe window
const rate = { windowStart: 0, count: 0 };

export async function POST(req: Request) {
  // Enablement is env-first (TRADINGVIEW_WEBHOOK_ENABLED=true) with a
  // dashboard switch (Settings → TradingView) as the alternative, so the
  // integration can be turned on without restarting the server.
  const settings = await getSettings();
  if (!flags.tradingviewWebhook() && !settings.tradingviewEnabled) {
    return Response.json(
      {
        error:
          "TradingView webhook integration is disabled. Enable it in Settings → TradingView (or set TRADINGVIEW_WEBHOOK_ENABLED=true).",
      },
      { status: 403 }
    );
  }

  // Simple rate limit: 30 requests / minute.
  const now = Date.now();
  if (now - rate.windowStart > 60000) {
    rate.windowStart = now;
    rate.count = 0;
  }
  rate.count += 1;
  if (rate.count > 30) {
    return Response.json({ error: "Rate limit exceeded" }, { status: 429 });
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON payload" }, { status: 400 });
  }

  // Secret: environment wins, otherwise the value saved in Settings.
  const secret = process.env.TRADINGVIEW_WEBHOOK_SECRET || settings.tradingviewSecret;
  const provided =
    req.headers.get("x-webhook-secret") ?? String(body.secret ?? "");
  if (!secret || provided !== secret) {
    await logAudit("webhook_rejected", { reason: "bad_secret" });
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  const tsRaw = body.timestamp ?? body.ts;
  const ts = typeof tsRaw === "number" ? tsRaw : Date.parse(String(tsRaw ?? ""));
  if (!Number.isFinite(ts) || Math.abs(Date.now() - ts) > 5 * 60000) {
    return Response.json({ error: "Stale or missing timestamp" }, { status: 400 });
  }

  const symbol = String(body.symbol ?? "").toUpperCase();
  const action = String(body.action ?? "").toUpperCase();
  if (!symbol || !["LONG", "SHORT", "CLOSE", "WATCH"].includes(action)) {
    return Response.json({ error: "Payload must include symbol and action LONG|SHORT|CLOSE|WATCH" }, { status: 400 });
  }

  const hash = `${symbol}:${action}:${ts}`;
  if (seen.has(hash)) {
    return Response.json({ ok: true, deduplicated: true });
  }
  seen.set(hash, now);
  for (const [k, v] of seen) if (now - v > 10 * 60000) seen.delete(k);

  const status =
    action === "LONG" ? "LONG_SETUP" : action === "SHORT" ? "SHORT_SETUP" : action === "WATCH" ? "WATCH" : "INVALIDATED";
  const price = typeof body.price === "number" ? body.price : 0;

  const row = await (await getRepo()).insertSignal({
    symbol,
    timeframe: String(body.timeframe ?? "15m") as SignalRow["timeframe"],
    strategy: `tradingview:${String(body.strategy ?? "external")}`,
    status: status as SignalRow["status"],
    price,
    entry: typeof body.entry === "number" ? body.entry : price || null,
    stop: typeof body.stop === "number" ? body.stop : null,
    target: typeof body.target === "number" ? body.target : null,
    rr: null,
    reasons: [String(body.message ?? "External TradingView alert (validated)")],
    outcome: "ACTIVE",
  });

  await logAudit("webhook_signal_accepted", { symbol, action });
  return Response.json({ ok: true, signalId: row.id });
}
