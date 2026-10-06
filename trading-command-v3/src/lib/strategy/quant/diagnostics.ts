/**
 * Regime + diagnostics + purged CV — ports of ml4t/regime.py,
 * diagnostic_part1/2.py, purged_cv.py. Pure functions, no deps.
 */
import type { Candle } from "@/lib/types";

/** Volatility-median fallback regime (== Python fallback when hmmlearn absent). */
export function regime(candles: Candle[], window = 20): "trend" | "range" {
  const rets: number[] = [];
  for (let i = 1; i < candles.length; i++) rets.push(candles[i].close / candles[i - 1].close - 1);
  const vols: number[] = rets.map((_, i) => {
    const w = rets.slice(Math.max(0, i - window + 1), i + 1);
    const m = w.reduce((a, b) => a + b, 0) / w.length;
    return Math.sqrt(w.reduce((a, b) => a + (b - m) ** 2, 0) / w.length);
  });
  const sorted = [...vols].sort((a, b) => a - b);
  const med = sorted[Math.floor(sorted.length / 2)] ?? 0;
  return (vols[vols.length - 1] ?? 0) > med ? "range" : "trend";
}

function rankAvg(v: number[]): number[] {
  const order = v.map((_, i) => i).sort((a, b) => v[a] - v[b]);
  const r = new Array(v.length).fill(0);
  let i = 0;
  while (i < v.length) {
    let j = i;
    while (j + 1 < v.length && v[order[j + 1]] === v[order[i]]) j++;
    for (let k = i; k <= j; k++) r[order[k]] = (i + j) / 2 + 1;
    i = j + 1;
  }
  return r;
}

export function spearmanIC(x: number[], y: number[]): { ic: number; n: number } {
  const pairs = x.map((v, i) => [v, y[i]] as const).filter(([a, b]) => isFinite(a) && isFinite(b));
  if (pairs.length < 30) return { ic: NaN, n: pairs.length };
  const rx = rankAvg(pairs.map((p) => p[0])), ry = rankAvg(pairs.map((p) => p[1]));
  const mx = rx.reduce((a, b) => a + b, 0) / rx.length, my = ry.reduce((a, b) => a + b, 0) / ry.length;
  let cov = 0, vx = 0, vy = 0;
  for (let i = 0; i < rx.length; i++) {
    cov += (rx[i] - mx) * (ry[i] - my); vx += (rx[i] - mx) ** 2; vy += (ry[i] - my) ** 2;
  }
  if (!vx || !vy) return { ic: NaN, n: pairs.length };
  return { ic: cov / Math.sqrt(vx * vy), n: pairs.length };
}

export function neweyWestSE(series: number[], lags?: number): number {
  const x = series.filter(isFinite);
  const n = x.length;
  if (n < 10) return NaN;
  const L = lags ?? Math.floor(4 * Math.pow(n / 100, 2 / 9));
  const mu = x.reduce((a, b) => a + b, 0) / n;
  const r = x.map((v) => v - mu);
  let s = r.reduce((a, b) => a + b * b, 0) / n;
  for (let lag = 1; lag <= Math.min(L, n - 1); lag++) {
    let g = 0;
    for (let i = lag; i < n; i++) g += r[i] * r[i - lag];
    s += 2 * (1 - lag / (L + 1)) * (g / n);
  }
  return Math.sqrt(Math.max(s, 0) / n);
}

const normSf = (z: number) => 0.5 * (1 - erf(z / Math.SQRT2));
function erf(x: number): number {
  const t = 1 / (1 + 0.5 * Math.abs(x));
  const tau = t * Math.exp(-x * x - 1.26551223 + t * (1.00002368 + t * (0.37409196 +
    t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 +
    t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return x >= 0 ? 1 - tau : tau - 1;
}

export function bhFdr(pValues: number[], alpha = 0.1): boolean[] {
  const order = pValues.map((_, i) => i).sort((a, b) => pValues[a] - pValues[b]);
  let cutoff = 0;
  order.forEach((idx, k) => { if (pValues[idx] <= ((k + 1) / pValues.length) * alpha) cutoff = k + 1; });
  const flags = new Array(pValues.length).fill(false);
  order.slice(0, cutoff).forEach((idx) => { flags[idx] = true; });
  return flags;
}

export const tToP = (t: number) => !isFinite(t) ? 1 : Math.max(0, Math.min(1, 2 * normSf(Math.abs(t))));

/** Purged walk-forward index splits with embargo (port of purged_cv.py). */
export function purgedSplits(n: number, nSplits = 4, embargoPct = 0.01): { train: number[]; test: number[] }[] {
  const size = Math.floor(n / nSplits);
  const bounds: number[][] = [];
  for (let k = 0; k < nSplits; k++) {
    const lo = k * size, hi = k === nSplits - 1 ? n : lo + size;
    bounds.push(Array.from({ length: hi - lo }, (_, i) => lo + i));
  }
  const out: { train: number[]; test: number[] }[] = [];
  for (let k = 1; k < nSplits; k++) {
    const test = bounds[k];
    const embargo = Math.max(1, Math.floor(test.length * embargoPct) + 1);
    const train = bounds.slice(0, k).flat().filter((i) => i < test[0] - embargo);
    if (train.length >= 50 && test.length) out.push({ train, test });
  }
  return out;
}
