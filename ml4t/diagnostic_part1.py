"""Part 1: Spearman IC, Newey-West HAC errors, BH-FDR, IC report."""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple
import numpy as np
import pandas as pd


def _rank_average(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    sv = values[order]
    i, n = 0, len(values)
    while i < n:
        j = i
        while j + 1 < n and sv[j + 1] == sv[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman_ic(x: np.ndarray, y: np.ndarray) -> Tuple[float, int]:
    x = np.asarray(x, dtype=float); y = np.asarray(y, dtype=float)
    m = ~(np.isnan(x) | np.isnan(y)); x, y = x[m], y[m]
    if len(x) < 30 or np.std(x) == 0 or np.std(y) == 0:
        return float("nan"), int(len(x))
    return float(np.corrcoef(_rank_average(x), _rank_average(y))[0, 1]), int(len(x))


def newey_west_se(series: np.ndarray, lags=None) -> float:
    x = np.asarray(series, dtype=float); x = x[~np.isnan(x)]; n = len(x)
    if n < 10:
        return float("nan")
    if lags is None:
        lags = int(math.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))
    resid = x - x.mean()
    s = float(np.dot(resid, resid) / n)
    for lag in range(1, min(lags, n - 1) + 1):
        s += 2.0 * (1.0 - lag / (lags + 1.0)) * float(np.dot(resid[lag:], resid[:-lag]) / n)
    return math.sqrt(max(s, 0.0) / n)


def hac_t_stat(series: np.ndarray, lags=None) -> float:
    mu = float(np.nanmean(series)); se = newey_west_se(np.asarray(series, dtype=float), lags)
    if not np.isfinite(se) or se == 0:
        return 0.0
    return mu / se


def _norm_sf(z: float) -> float:
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def t_to_p_two_sided(t: float) -> float:
    if not np.isfinite(t):
        return 1.0
    return max(0.0, min(1.0, 2.0 * _norm_sf(abs(t))))


def bh_fdr(p_values: Sequence[float], alpha: float = 0.10) -> List[bool]:
    p = np.asarray(list(p_values), dtype=float); m = len(p)
    if m == 0:
        return []
    order = np.argsort(p, kind="mergesort"); ranked = p[order]
    flags = np.zeros(m, dtype=bool); cutoff = 0
    for k in range(1, m + 1):
        if ranked[k - 1] <= (k / m) * alpha:
            cutoff = k
    if cutoff:
        flags[order[:cutoff]] = True
    return [bool(v) for v in flags]


@dataclass
class ICRow:
    predictor: str; horizon: str; ic: float; n: int
    hac_t: float; p_value: float; fdr_pass: bool = False


@dataclass
class ICReport:
    rows: List[ICRow] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"{'predictor':>14}{'horizon':>9}{'IC':>9}{'HAC-t':>8}{'p':>9}  FDR"]
        for r in self.rows:
            lines.append(f"{r.predictor:>14}{r.horizon:>9}{r.ic:>9.4f}"
                         f"{r.hac_t:>8.2f}{r.p_value:>9.4f}  {'PASS' if r.fdr_pass else '-'}")
        return "\n".join(lines)


def _ic_series(signal: np.ndarray, fwd: np.ndarray, chunk: int = 50) -> np.ndarray:
    out = []
    step = max(1, chunk // 2)  # overlapping rolling windows: more HAC samples
    for s in range(0, len(signal) - chunk + 1, step):
        ic, _ = spearman_ic(signal[s:s + chunk], fwd[s:s + chunk])
        if np.isfinite(ic):
            out.append(ic)
    return np.asarray(out, dtype=float)


def ic_report(signals: pd.DataFrame, forwards: pd.DataFrame,
              fdr_alpha: float = 0.10) -> ICReport:
    rows: List[ICRow] = []; pvals: List[float] = []
    for pred in signals.columns:
        s = signals[pred].to_numpy(dtype=float)
        for horizon in forwards.columns:
            f = forwards[horizon].to_numpy(dtype=float)
            ic, n = spearman_ic(s, f)
            series = _ic_series(s, f)
            t = hac_t_stat(series) if len(series) >= 4 else 0.0
            p = t_to_p_two_sided(t); pvals.append(p)
            rows.append(ICRow(str(pred), str(horizon), ic, n, t, p))
    for row, flag in zip(rows, bh_fdr(pvals, alpha=fdr_alpha)):
        row.fdr_pass = flag
    return ICReport(rows=rows)
