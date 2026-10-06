/**
 * Deterministic demo market simulator.
 *
 * Prices are a pure function of time (layered waves + interpolated hash noise),
 * so every timeframe and every request is consistent, candles "print" live as
 * time advances, and no state is required. Demo data is always labelled
 * `source: "demo"` — it must never be presented as live exchange data.
 */
import type { Candle, OrderBook, RecentTrade, Ticker, Timeframe } from "../types";
import { TF_MINUTES } from "../types";

export interface SymbolDef {
  symbol: string;
  base: number;
  volMult: number;
  tick: number;
  seed: number;
  volBase: number; // contracts per minute baseline
}

export const DEMO_SYMBOLS: SymbolDef[] = [
  { symbol: "BTCUSD", base: 108420, volMult: 1.0, tick: 0.5, seed: 7, volBase: 620 },
  { symbol: "ETHUSD", base: 3864, volMult: 1.35, tick: 0.05, seed: 13, volBase: 5200 },
  { symbol: "SOLUSD", base: 214.8, volMult: 1.7, tick: 0.01, seed: 29, volBase: 38000 },
  { symbol: "XRPUSD", base: 2.421, volMult: 1.9, tick: 0.0001, seed: 41, volBase: 900000 },
];

export function symbolDef(symbol: string): SymbolDef {
  return (
    DEMO_SYMBOLS.find((s) => s.symbol === symbol) ?? {
      symbol,
      base: 100,
      volMult: 1.4,
      tick: 0.01,
      seed: symbol.length * 17 + 3,
      volBase: 10000,
    }
  );
}

function hash01(n: number): number {
  const x = Math.sin(n * 127.1 + 311.7) * 43758.5453;
  return x - Math.floor(x);
}

function valueNoise(t: number, seed: number, period: number): number {
  const x = t / period;
  const i = Math.floor(x);
  const f = x - i;
  const u = f * f * (3 - 2 * f);
  const a = hash01(i * 57.31 + seed * 913.7);
  const b = hash01((i + 1) * 57.31 + seed * 913.7);
  return (a + (b - a) * u) * 2 - 1; // -1..1
}

/** Price in USD at a fractional minute offset from epoch. */
export function priceAt(def: SymbolDef, minuteFloat: number): number {
  const t = minuteFloat;
  const s = def.seed;
  const slow =
    0.052 * Math.sin(t / 660 + s) +
    0.026 * Math.sin(t / 217 + s * 2.3) +
    0.011 * Math.sin(t / 63 + s * 0.7);
  const n1 = valueNoise(t, s, 12) * 0.0038 * def.volMult;
  const n2 = valueNoise(t, s + 5, 3.9) * 0.0013 * def.volMult;
  return def.base * Math.exp(slow * def.volMult + n1 + n2);
}

function volAt(def: SymbolDef, minuteFloat: number): number {
  const burst = Math.pow(Math.abs(valueNoise(minuteFloat, def.seed + 9, 9)), 2.2);
  return def.volBase * (0.35 + 0.65 * burst);
}

function candleFor(def: SymbolDef, startMinute: number, tfMin: number): Candle {
  const open = priceAt(def, startMinute);
  const close = priceAt(def, startMinute + tfMin);
  const steps = Math.min(tfMin, 8);
  let high = Math.max(open, close);
  let low = Math.min(open, close);
  for (let k = 1; k < steps; k++) {
    const p = priceAt(def, startMinute + (tfMin * k) / steps);
    if (p > high) high = p;
    if (p < low) low = p;
  }
  const wickUp = hash01(startMinute * 1.7 + def.seed) * 0.0009 * def.volMult;
  const wickDn = hash01(startMinute * 2.3 + def.seed + 11) * 0.0009 * def.volMult;
  high *= 1 + wickUp;
  low *= 1 - wickDn;
  const move = Math.abs(close - open) / open;
  const volume =
    volAt(def, startMinute + tfMin / 2) * tfMin * (1 + move * 900) *
    (0.7 + 0.6 * hash01(startMinute + def.seed * 3));
  return {
    time: startMinute * 60,
    open: roundTick(open, def.tick),
    high: roundTick(high, def.tick),
    low: roundTick(low, def.tick),
    close: roundTick(close, def.tick),
    volume: Math.round(volume),
  };
}

function roundTick(p: number, tick: number): number {
  const r = Math.round(p / tick) * tick;
  const dec = tick >= 1 ? 1 : tick >= 0.01 ? 2 : tick >= 0.001 ? 3 : 5;
  return Number(r.toFixed(dec));
}

export function demoCandles(symbol: string, timeframe: Timeframe, count: number): Candle[] {
  const def = symbolDef(symbol);
  const tfMin = TF_MINUTES[timeframe];
  const nowMinute = Date.now() / 60000;
  const lastStart = Math.floor(nowMinute / tfMin) * tfMin; // forming candle
  const out: Candle[] = [];
  for (let i = count - 1; i >= 0; i--) {
    out.push(candleFor(def, lastStart - i * tfMin, tfMin));
  }
  return out;
}

export function demoTicker(symbol: string): Ticker {
  const def = symbolDef(symbol);
  const now = Date.now() / 60000;
  const price = priceAt(def, now);
  const prev = priceAt(def, now - 1440);
  let high = price;
  let low = price;
  for (let k = 1; k <= 96; k++) {
    const p = priceAt(def, now - (1440 * k) / 96);
    if (p > high) high = p;
    if (p < low) low = p;
  }
  let vol = 0;
  for (let k = 0; k < 48; k++) vol += volAt(def, now - 30 * k) * 30;
  const spread = Math.max(def.tick, price * 0.00012);
  const dayFrac = (Date.now() / 1000) % 86400;
  return {
    symbol,
    price: roundTick(price, def.tick),
    markPrice: roundTick(price * (1 + 0.00006 * Math.sin(now / 7)), def.tick),
    change24hPct: ((price - prev) / prev) * 100,
    volume24hUsd: vol * price,
    fundingRate: 0.008 + 0.017 * Math.sin(dayFrac / 86400 * Math.PI * 2 + def.seed),
    openInterest: vol * price * (0.32 + 0.05 * Math.sin(now / 240 + def.seed)),
    high24h: roundTick(high, def.tick),
    low24h: roundTick(low, def.tick),
    bid: roundTick(price - spread / 2, def.tick),
    ask: roundTick(price + spread / 2, def.tick),
    ts: Date.now(),
    source: "demo",
  };
}

export function demoOrderbook(symbol: string): OrderBook {
  const def = symbolDef(symbol);
  const t = demoTicker(symbol);
  const step = Math.max(def.tick, t.price * 0.00022);
  const bids = [];
  const asks = [];
  for (let i = 1; i <= 14; i++) {
    const bh = hash01(i * 3.1 + def.seed + Math.floor(t.price / step) * 0.013);
    const ah = hash01(i * 5.7 + def.seed * 2 + Math.floor(t.price / step) * 0.017);
    const wall = (h: number) => (h > 0.93 ? 6 : 1);
    bids.push({
      price: roundTick(t.price - step * i, def.tick),
      size: Number((def.volBase * 0.03 * (0.25 + bh) * wall(bh)).toFixed(4)),
    });
    asks.push({
      price: roundTick(t.price + step * i, def.tick),
      size: Number((def.volBase * 0.03 * (0.25 + ah) * wall(ah)).toFixed(4)),
    });
  }
  return { symbol, bids, asks, ts: Date.now(), source: "demo" };
}

export function demoTrades(symbol: string): RecentTrade[] {
  const def = symbolDef(symbol);
  const t = demoTicker(symbol);
  const now = Date.now();
  const out: RecentTrade[] = [];
  for (let i = 0; i < 22; i++) {
    const h1 = hash01(now / 1000 + i * 13.7 + def.seed);
    const h2 = hash01(now / 1000 + i * 7.9 + def.seed * 3);
    out.push({
      price: roundTick(t.price + (h1 - 0.5) * t.price * 0.0003, def.tick),
      size: Number((def.volBase * 0.02 * (0.2 + h2)).toFixed(4)),
      side: h1 > 0.5 ? "buy" : "sell",
      ts: now - i * (900 + Math.floor(h2 * 2600)),
    });
  }
  return out;
}
