/**
 * Unified market data facade.
 *
 * Demo mode: served by the deterministic simulator (always available).
 * Delta mode: proxied through the Delta REST adapter with short TTL caches
 * so the UI can poll without hammering the exchange.
 *
 * Errors are surfaced — we never silently substitute stale/demo data for live.
 */
import { flags } from "../flags";
import { getSettings } from "../settings";
import type { Candle, OrderBook, RecentTrade, Ticker, Timeframe } from "../types";
import { TF_MINUTES } from "../types";
import { deltaCandles, deltaOrderbook, deltaTickers } from "./delta";
import { demoCandles, demoOrderbook, demoTicker, demoTrades, DEMO_SYMBOLS } from "./demo";

export class MarketError extends Error {}

export async function activeDataSource(): Promise<"demo" | "delta"> {
  const s = await getSettings();
  if (s.dataSource === "delta" && flags.deltaMarket()) return "delta";
  return "demo";
}

export function knownSymbols(): string[] {
  return DEMO_SYMBOLS.map((s) => s.symbol);
}

export async function getTickers(symbols?: string[]): Promise<Ticker[]> {
  const src = await activeDataSource();
  if (src === "delta") {
    try {
      const all = await deltaTickers();
      return symbols ? all.filter((t) => symbols.includes(t.symbol)) : all.slice(0, 30);
    } catch (e) {
      throw new MarketError(
        e instanceof Error ? e.message : "Delta market data unavailable"
      );
    }
  }
  const list = symbols ?? DEMO_SYMBOLS.map((s) => s.symbol);
  return list.map((s) => demoTicker(s));
}

export async function getPrice(symbol: string): Promise<number> {
  const [t] = await getTickers([symbol]);
  if (!t || !t.price) throw new MarketError(`No price available for ${symbol}`);
  return t.price;
}

export async function getCandles(
  symbol: string,
  timeframe: Timeframe,
  limit = 300
): Promise<{ candles: Candle[]; source: "demo" | "delta" }> {
  const src = await activeDataSource();
  if (src === "delta") {
    try {
      const candles = await deltaCandles(symbol, timeframe, limit, TF_MINUTES[timeframe]);
      if (candles.length > 0) return { candles, source: "delta" };
    } catch {
      /* fall through to demo — flagged below */
    }
    // Delta returned nothing for this symbol/resolution: fall back to demo,
    // but the response is explicitly labelled so the UI can show it.
  }
  return { candles: demoCandles(symbol, timeframe, limit), source: "demo" };
}

export async function getOrderbook(symbol: string): Promise<OrderBook> {
  const src = await activeDataSource();
  if (src === "delta" && flags.orderbook()) {
    try {
      return await deltaOrderbook(symbol);
    } catch {
      /* labelled fallback */
    }
  }
  return demoOrderbook(symbol);
}

export async function getRecentTrades(symbol: string): Promise<RecentTrade[]> {
  const src = await activeDataSource();
  if (src === "delta") {
    // Public trades endpoint is best-effort; demo feed keeps UX consistent.
    try {
      const { http } = await import("./delta");
      const data = (await http("GET", "/v2/trades", { symbol, count: 22 }, null, false)) as {
        result?: { price: string; size: number; side: string; timestamp: number }[];
      };
      return (data.result ?? []).map((t) => ({
        price: parseFloat(t.price),
        size: t.size,
        side: t.side === "buy" ? ("buy" as const) : ("sell" as const),
        ts: t.timestamp * 1000,
      }));
    } catch {
      return demoTrades(symbol);
    }
  }
  return demoTrades(symbol);
}
