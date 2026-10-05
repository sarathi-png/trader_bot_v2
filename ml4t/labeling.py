"""Triple-barrier labels + meta-labels (Jansen / Lopez de Prado pattern).

primary: first touch of upper / lower barrier (ATR multiples) or time stop.
meta: +1 when a primary LONG/SHORT was profitable net of costs, else 0.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BarrierConfig:
    atr_mult: float = 1.5
    r_multiple: float = 2.0
    max_hold: int = 48
    fee_pct: float = 0.059
    slippage_pct: float = 0.02


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["high"] - df["low"]
    hc = (df["high"] - df["close"].shift(1)).abs()
    lc = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def triple_barrier_labels(df: pd.DataFrame,
                          cfg: BarrierConfig = BarrierConfig()) -> pd.DataFrame:
    n = len(df)
    atr = _atr(df).to_numpy(float)
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float); low = df["low"].to_numpy(float)
    opens = df["open"].to_numpy(float)
    out = pd.DataFrame(index=df.index,
                       columns=["primary", "meta_long", "meta_short",
                                "ret_long", "ret_short"], dtype=float)
    cost = (cfg.fee_pct + cfg.slippage_pct) / 100.0 * 2.0
    for i in range(n):
        if not np.isfinite(atr[i]) or atr[i] <= 0 or i + 1 >= n:
            continue
        entry = opens[i + 1]
        up = entry + cfg.atr_mult * atr[i]
        dn = entry - cfg.atr_mult * atr[i]
        tp_l = entry + cfg.r_multiple * (entry - dn)
        tp_s = entry - cfg.r_multiple * (up - entry)
        end = min(n - 1, i + cfg.max_hold)
        # Independent per-side simulation: each side gets its own
        # stop/profit barriers so meta labels are not self-fulfilling.
        r_long, r_short, prim = np.nan, np.nan, 0
        touched_up = touched_dn = False
        for j in range(i + 1, end + 1):
            if not touched_up and high[j] >= up:
                touched_up = True
            if not touched_dn and low[j] <= dn:
                touched_dn = True
            if np.isnan(r_long):
                if low[j] <= dn:
                    r_long = -(entry - dn) / entry - cost
                elif high[j] >= tp_l:
                    r_long = (tp_l - entry) / entry - cost
            if np.isnan(r_short):
                if high[j] >= up:
                    r_short = -(up - entry) / entry - cost
                elif low[j] <= tp_s:
                    r_short = (entry - tp_s) / entry - cost
            if not np.isnan(r_long) and not np.isnan(r_short):
                break
        if np.isnan(r_long):
            r_long = (close[end] - entry) / entry - cost
        if np.isnan(r_short):
            r_short = (entry - close[end]) / entry - cost
        if touched_up and not touched_dn:
            prim = 1
        elif touched_dn and not touched_up:
            prim = -1
        out.iloc[i] = [prim, 1.0 if r_long > 0 else 0.0,
                       1.0 if r_short > 0 else 0.0, r_long, r_short]
    return out
