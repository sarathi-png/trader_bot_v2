"""Part 2: quantile spreads, Deflated Sharpe Ratio, PBO."""
from __future__ import annotations
import math
from dataclasses import dataclass
from typing import Dict, List
import numpy as np
import pandas as pd
from ml4t.diagnostic_part1 import hac_t_stat, _norm_sf as _sf


@dataclass
class QuantileSpread:
    horizon: str; top_mean: float; bottom_mean: float; spread: float
    spread_hac_t: float; n_top: int; n_bottom: int


def quantile_spread(signed_signal: np.ndarray, forwards: pd.DataFrame,
                    quantiles: int = 5) -> List[QuantileSpread]:
    s = np.asarray(signed_signal, dtype=float); out: List[QuantileSpread] = []
    try:
        buckets = np.asarray(pd.qcut(pd.Series(s), quantiles, labels=False, duplicates="drop"))
    except ValueError:
        return out
    if buckets.max() == buckets.min():
        return out
    top = buckets == buckets.max(); bot = buckets == buckets.min()
    for horizon in forwards.columns:
        f = forwards[horizon].to_numpy(dtype=float)
        hi = f[top & np.isfinite(f)]; lo = f[bot & np.isfinite(f)]
        if len(hi) < 10 or len(lo) < 10:
            continue
        spread = float(np.mean(hi) - np.mean(lo))
        t = hac_t_stat(np.concatenate([hi - np.mean(lo), -(lo - np.mean(hi))]))
        out.append(QuantileSpread(str(horizon), float(np.mean(hi)), float(np.mean(lo)),
                                  spread, t, len(hi), len(lo)))
    return out


def _norm_ppf(p: float) -> float:
    p = max(1e-12, min(1.0 - 1e-12, p))
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= phigh:
        q = p - 0.5; r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def deflated_sharpe(returns: np.ndarray, trials: int) -> Dict[str, float]:
    r = np.asarray(returns, dtype=float); r = r[np.isfinite(r)]; n = len(r)
    if n < 10:
        return {"dsr": float("nan"), "sr": float("nan"),
                "trials": float(trials), "n": float(n)}
    mu = float(r.mean()); sd = float(r.std(ddof=1)); sr = mu / sd if sd > 0 else 0.0
    skew = float(pd.Series(r).skew()); kurt = float(pd.Series(r).kurtosis())
    gamma, e = 0.5772156649, math.e
    sr0 = (1.0 - gamma) * _norm_ppf(1.0 - 1.0 / max(trials, 2)) + gamma * _norm_ppf(1.0 - 1.0 / (max(trials, 2) * e)) if trials >= 2 else 0.0
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt / 4.0) * sr * sr))
    dsr = 1.0 - _sf((sr - sr0) * math.sqrt(max(n - 1, 1)) / denom) if denom > 0 else 0.0
    return {"dsr": float(min(1.0, max(0.0, dsr))), "sr": float(sr),
            "sr0_null": float(sr0), "skew": float(skew),
            "kurtosis": float(kurt), "trials": float(trials), "n": float(n)}


def pbo_score(returns_matrix: pd.DataFrame, n_splits: int = 8) -> Dict[str, float]:
    mat = np.asarray(returns_matrix, dtype=float); t, n = mat.shape
    if t < 4 * n_splits or n < 2:
        return {"pbo": float("nan"), "n_variants": float(n),
                "n_periods": float(t), "n_splits_used": 0.0}
    rng = np.random.default_rng(42); bounds = np.array_split(np.arange(t), n_splits)
    n_combos = min(64, 2 ** (n_splits - 1)); ranks = []
    for _ in range(n_combos):
        mask = rng.integers(0, 2, size=n_splits).astype(bool)
        if mask.all() or not mask.any():
            mask[0] = True; mask[-1] = False
        is_idx = np.concatenate([bounds[k] for k in range(n_splits) if mask[k]])
        oos_idx = np.concatenate([bounds[k] for k in range(n_splits) if not mask[k]])
        is_sr = mat[is_idx].mean(axis=0) / (mat[is_idx].std(axis=0, ddof=1) + 1e-12)
        oos_sr = mat[oos_idx].mean(axis=0) / (mat[oos_idx].std(axis=0, ddof=1) + 1e-12)
        best = int(np.nanargmax(is_sr))
        ranks.append(float(np.sum(oos_sr >= oos_sr[best])) / n)
    return {"pbo": float(np.mean(np.asarray(ranks) > 0.5)), "n_variants": float(n),
            "n_periods": float(t), "n_splits_used": float(n_combos)}
