/**
 * GET /api/delta/summary — exchange account analytics for the dashboard.
 *
 * Returns wallet balance (USD and INR), cumulative deposits/withdrawals,
 * realized P&L with best/worst round-trip trade derived from the fill
 * stream, plus fees. Never throws: an unconfigured or unreachable venue
 * returns 200 with `available: false` and an `error` string so the UI can
 * explain itself instead of breaking.
 */
import { getDeltaSummary } from "@/lib/deltaAccount";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export async function GET() {
  try {
    const summary = await getDeltaSummary();
    return Response.json(summary);
  } catch (e) {
    return Response.json(
      {
        available: false,
        error: e instanceof Error ? e.message : "Summary unavailable",
        balanceUsd: 0,
        balanceInr: 0,
        balances: [],
        depositsUsd: 0,
        withdrawalsUsd: 0,
        realizedPnlUsd: 0,
        realizedPnlInr: 0,
        tradeCount: 0,
        winRate: null,
        bestTradeUsd: null,
        worstTradeUsd: null,
        avgTradeUsd: null,
        fillCount: 0,
        recentTrades: [],
        topSymbols: [],
      },
      { status: 200 }
    );
  }
}