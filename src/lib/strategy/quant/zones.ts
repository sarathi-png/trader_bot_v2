/**
 * S/R zones — faithful port of trader_bot_v2/engine/sr_zones.py.
 *
 * Python semantics replicated here:
 *  - swings: `high == rolling(2n+1, center=True).max()` — EQUALITY, so tied
 *    bars count as swings (unlike a strict-comparison implementation);
 *    first/last n bars can never be confirmed swings.
 *  - clustering: prices sorted, grouped while within tolerance of the running
 *    cluster MEAN, each zone emitted as a (low, high) tuple.
 *  - nearest support = zone whose HIGH edge is closest to price;
 *    nearest resistance = zone whose LOW edge is closest to price.
 *    (Deliberately side-agnostic: a just-broken zone is still relevant.)
 */
import type { Candle } from "@/lib/types";

export interface Zone { low: number; high: number }

/** Boolean swing flags, matching find_swing_high_low(). */
export function swingFlags(candles: Candle[], n = 5): { swingHigh: boolean[]; swingLow: boolean[] } {
  const len = candles.length;
  const swingHigh = new Array(len).fill(false);
  const swingLow = new Array(len).fill(false);
  for (let i = n; i < len - n; i++) {
    let hi = -Infinity;
    let lo = Infinity;
    for (let j = i - n; j <= i + n; j++) {
      if (candles[j].high > hi) hi = candles[j].high;
      if (candles[j].low < lo) lo = candles[j].low;
    }
    if (candles[i].high === hi) swingHigh[i] = true;
    if (candles[i].low === lo) swingLow[i] = true;
  }
  return { swingHigh, swingLow };
}

/** Confirmed swing prices (chronological). */
export function findSwings(candles: Candle[], n = 5): { highs: number[]; lows: number[] } {
  const { swingHigh, swingLow } = swingFlags(candles, n);
  const highs: number[] = [];
  const lows: number[] = [];
  candles.forEach((c, i) => {
    if (swingHigh[i]) highs.push(c.high);
    if (swingLow[i]) lows.push(c.low);
  });
  return { highs, lows };
}

/** Cluster swing prices into (low, high) zones on the cluster mean. */
export function clusterZones(levels: number[], tolPct = 0.003): Zone[] {
  if (!levels.length) return [];
  const sorted = [...levels].sort((a, b) => a - b);
  const zones: Zone[] = [];
  let cluster: number[] = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    const center = cluster.reduce((a, b) => a + b, 0) / cluster.length;
    if (Math.abs(sorted[i] - center) / center <= tolPct) {
      cluster.push(sorted[i]);
    } else {
      zones.push({ low: Math.min(...cluster), high: Math.max(...cluster) });
      cluster = [sorted[i]];
    }
  }
  zones.push({ low: Math.min(...cluster), high: Math.max(...cluster) });
  return zones;
}

export function supportResZones(candles: Candle[], n = 5, tolPct = 0.003): { supZones: Zone[]; resZones: Zone[] } {
  const { highs, lows } = findSwings(candles, n);
  return { supZones: clusterZones(lows, tolPct), resZones: clusterZones(highs, tolPct) };
}

/** Zone HIGH edge nearest price (support side). */
export function nearestSupport(candles: Candle[], n = 5, tolPct = 0.003): number | null {
  const close = candles[candles.length - 1].close;
  const { supZones } = supportResZones(candles, n, tolPct);
  let best: number | null = null;
  let bestDist = Infinity;
  for (const z of supZones) {
    const d = Math.abs(close - z.high);
    if (d < bestDist) { bestDist = d; best = z.high; }
  }
  return best;
}

/** Zone LOW edge nearest price (resistance side). */
export function nearestResistance(candles: Candle[], n = 5, tolPct = 0.003): number | null {
  const close = candles[candles.length - 1].close;
  const { resZones } = supportResZones(candles, n, tolPct);
  let best: number | null = null;
  let bestDist = Infinity;
  for (const z of resZones) {
    const d = Math.abs(close - z.low);
    if (d < bestDist) { bestDist = d; best = z.low; }
  }
  return best;
}

/** Convenience: both nearest levels. */
export function nearestZones(candles: Candle[], n = 5, tolPct = 0.003): { support: number | null; resistance: number | null } {
  return { support: nearestSupport(candles, n, tolPct), resistance: nearestResistance(candles, n, tolPct) };
}

/**
 * S/R levels as used by ml4t/features.py: the most recent confirmed swing
 * low/high at or before each bar, carried forward (ffill).
 */
export function swingLevelFfill(candles: Candle[], n = 5): { support: (number | null)[]; resistance: (number | null)[] } {
  const { swingHigh, swingLow } = swingFlags(candles, n);
  const support: (number | null)[] = [];
  const resistance: (number | null)[] = [];
  let lastSupport: number | null = null;
  let lastResistance: number | null = null;
  candles.forEach((c, i) => {
    if (swingLow[i]) lastSupport = c.low;
    if (swingHigh[i]) lastResistance = c.high;
    support.push(lastSupport);
    resistance.push(lastResistance);
  });
  return { support, resistance };
}

/**
 * Structure trend from swing points (port of trendlines.get_trend_direction):
 * compares the two most recent confirmed swing highs/lows.
 */
export function trendDirection(candles: Candle[], n = 5): "uptrend" | "downtrend" | "ranging" {
  const { highs, lows } = findSwings(candles, n);
  const rh = highs.slice(-n);
  const rl = lows.slice(-n);
  if (rh.length < 2 || rl.length < 2) return "ranging";
  const hh = rh[rh.length - 1] > rh[rh.length - 2];
  const hl = rl[rl.length - 1] > rl[rl.length - 2];
  const lh = rh[rh.length - 1] < rh[rh.length - 2];
  const ll = rl[rl.length - 1] < rl[rl.length - 2];
  if (hh && hl) return "uptrend";
  if (lh && ll) return "downtrend";
  return "ranging";
}