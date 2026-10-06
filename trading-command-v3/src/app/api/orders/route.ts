/**
 * LIVE order endpoint.
 *
 * Four independent gates must all pass before anything is sent:
 *   1. LIVE_EXECUTION_ENABLED=true (environment)
 *   2. settings.mode === "live"
 *   3. settings.liveArmed === true (master switch, confirmation token)
 *   4. Delta credentials configured
 *
 * Then the order must clear the SAME risk evaluation that guards paper fills
 * (see lib/risk.ts), and it carries a client_order_id so a retry returns the
 * original result instead of placing a second order.
 *
 * Authentication is enforced for every /api route by middleware.ts and is not
 * duplicated here. Default configuration is always 403.
 */
import { getRepo } from "@/lib/repo";
import { deltaAccountConfigured } from "@/lib/credentials";
import { flags } from "@/lib/flags";
import { http, deltaPositions, deltaTickers, deltaWalletBalances } from "@/lib/market/delta";
import { evaluateOrderRisk, normalizeRiskLimits } from "@/lib/risk";
import { getSettings, logAudit } from "@/lib/settings";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/**
 * Realised P&L since UTC midnight for the live account.
 *
 * NOT IMPLEMENTED — returns null, which the risk layer treats as "unknown" and
 * therefore blocks. A daily-loss limit that assumes zero realised loss is not a
 * limit, so live orders stay closed until this reads actual fills from the
 * exchange (sum realised_pnl over today's fills) and caches it.
 */
async function liveRealizedPnlToday(): Promise<number | null> {
  return null;
}

export async function GET() {
  const settings = await getSettings();
  return Response.json({
    liveExecutionFlag: flags.liveExecution(),
    mode: settings.mode,
    liveArmed: settings.liveArmed,
    deltaConfigured: await deltaAccountConfigured(),
  });
}

export async function POST(req: Request) {
  const settings = await getSettings();

  if (!flags.liveExecution()) {
    await logAudit("live_order_rejected", { reason: "flag_disabled" });
    return Response.json(
      { error: "Live execution is disabled by configuration (LIVE_EXECUTION_ENABLED=false)." },
      { status: 403 }
    );
  }
  if (settings.mode !== "live" || !settings.liveArmed) {
    await logAudit("live_order_rejected", { reason: "not_armed", mode: settings.mode });
    return Response.json(
      { error: "Live trading is not armed. Enable LIVE mode and the master switch first." },
      { status: 403 }
    );
  }
  if (!(await deltaAccountConfigured())) {
    return Response.json({ error: "Delta API credentials are not configured." }, { status: 403 });
  }

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return Response.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const symbol = String(body.symbol ?? "").toUpperCase();
  const side = body.side === "sell" ? "sell" : "buy";
  const type = body.type === "limit_order" ? "limit_order" : "market_order";
  const size = Math.abs(Number(body.size) || 0);
  const reduceOnly = Boolean(body.reduce_only);
  const limitPrice = typeof body.limit_price === "number" ? body.limit_price : null;

  if (!symbol || size <= 0) {
    return Response.json({ error: "symbol and positive size are required" }, { status: 400 });
  }

  // ---- idempotency ------------------------------------------------------
  // A retried request must return the first result, never place a second order.
  const clientOrderId =
    typeof body.client_order_id === "string" && body.client_order_id.trim()
      ? body.client_order_id.trim()
      : `tc-${Date.now()}-${crypto.randomUUID()}`;

  const existing = await (await getRepo()).findLiveOrderByClientId(clientOrderId);
  if (existing) {
    await logAudit("live_order_deduplicated", { clientOrderId, symbol });
    return Response.json({
      ok: true,
      deduplicated: true,
      clientOrderId,
      order: existing.response,
    });
  }
  // ---- reference price for the risk maths --------------------------------
  let referencePrice: number;
  try {
    if (type === "limit_order" && limitPrice !== null) {
      referencePrice = limitPrice;
    } else {
      const tickers = await deltaTickers();
      const found = tickers.find((t) => t.symbol === symbol);
      referencePrice = found?.price ?? 0;
    }
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Could not read a reference price";
    await logAudit("live_order_failed", { clientOrderId, symbol, error: msg });
    return Response.json({ error: msg }, { status: 502 });
  }

  // ---- risk evaluation ---------------------------------------------------
  const limits = normalizeRiskLimits(settings.riskLimits);
  let openSymbols: string[] = [];
  let currentNotional = 0;
  let equity = 0;
  try {
    const [positions, balances] = await Promise.all([deltaPositions(), deltaWalletBalances()]);
    openSymbols = positions.map((p) => p.symbol);
    currentNotional = positions.reduce(
      (a, p) => a + Math.abs(p.qty) * (p.mark || p.entry),
      0
    );
    const usd = balances.find((b) => b.asset === "USD" || b.asset === "USDC");
    equity = usd?.balance ?? 0;
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Could not read live account state";
    await logAudit("live_order_failed", { clientOrderId, symbol, error: msg });
    return Response.json({ error: msg }, { status: 502 });
  }

  const verdict = evaluateOrderRisk(
    { symbol, qty: size, price: referencePrice, reduceOnly },
    {
      limits,
      openSymbols,
      currentNotional,
      equity,
      dailyRealizedPnl: await liveRealizedPnlToday(),
    }
  );
  if (!verdict.allowed) {
    await logAudit("risk_block_triggered", {
      scope: "live",
      clientOrderId,
      symbol,
      side,
      size,
      code: verdict.code,
      reason: verdict.reason,
    });
    return Response.json(
      { error: `Blocked by risk limit: ${verdict.reason}`, code: verdict.code },
      { status: 403 }
    );
  }

  // ---- claim the idempotency key, then submit ----------------------------
  const repo = await getRepo();
  await repo.insertLiveOrder({
    clientOrderId,
    symbol,
    side,
    type,
    size,
    price: referencePrice,
    status: "pending",
  });

  try {
    const product = (await http("GET", `/v2/products/${symbol}`, {}, null, false)) as {
      result?: { id?: number };
    };
    const productId = product.result?.id;
    if (!productId) throw new Error(`Product ${symbol} not found on Delta`);

    const payload: Record<string, unknown> = {
      product_id: productId,
      order_type: type,
      side,
      size,
      reduce_only: reduceOnly,
      // Echoed by the exchange so a retry maps back to the same order.
      client_order_id: clientOrderId,
    };
    if (type === "limit_order" && limitPrice !== null) {
      payload.limit_price = String(limitPrice);
    }

    const res = (await http("POST", "/v2/orders", {}, payload, true)) as {
      result?: Record<string, unknown>;
    };

    await repo.updateLiveOrderByClientId(clientOrderId, {
      status: "submitted",
      response: (res.result ?? null) as Record<string, unknown> | null,
    });

    await logAudit("live_order_placed", { clientOrderId, symbol, side, type, size });
    return Response.json({ ok: true, clientOrderId, order: res.result });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Live order failed";
    await repo.updateLiveOrderByClientId(clientOrderId, { status: "failed" });
    await logAudit("live_order_failed", { clientOrderId, symbol, error: msg });
    return Response.json({ error: msg }, { status: 502 });
  }
}