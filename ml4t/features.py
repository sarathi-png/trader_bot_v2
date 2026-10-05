"""Causal feature engineering: ATR/RSI/MA/SR/trendline/volume features.

Every feature at row i uses only candles <= i (no look-ahead). Assembled
for LightGBM training and for live scoring (tail row of the frame).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from engine.indicators import atr_14, ma_cross, rsi

FEATURE_COLUMNS = [
    "atr_norm", "rsi_14", "rsi_dist50", "ema_fast", "ema_slow",
    "ema_gap_atr", "ma_fast", "ma_slow", "ma_gap_atr", "ma_cross",
    "dist_support_atr", "dist_resist_atr", "wick_reject",
    "trend_slope_atr", "vol_ratio", "ret_1", "ret_4", "range_atr",
]


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def build_features(df: pd.DataFrame, swing_n: int = 5,
                   tol_pct: float = 0.003) -> pd.DataFrame:
    f = df.copy()
    close, high, low = f["close"], f["high"], f["low"]
    atr = atr_14(f).replace(0, np.nan).ffill()
    f["atr_norm"] = atr / close
    r = rsi(f); f["rsi_14"] = r; f["rsi_dist50"] = (r - 50.0) / 50.0
    ef, es = _ema(close, 20), _ema(close, 50)
    f["ema_fast"] = ef / close - 1.0; f["ema_slow"] = es / close - 1.0
    f["ema_gap_atr"] = (ef - es) / atr
    sma_f = close.rolling(9).mean(); sma_s = close.rolling(21).mean()
    f["ma_fast"] = sma_f / close - 1.0; f["ma_slow"] = sma_s / close - 1.0
    f["ma_gap_atr"] = (sma_f - sma_s) / atr
    mc = ma_cross(f)
    f["ma_cross"] = mc["ma_cross_signal"].astype(float)
    roll_hi = high.rolling(swing_n * 2 + 1, center=True).max()
    roll_lo = low.rolling(swing_n * 2 + 1, center=True).min()
    is_hi = (high == roll_hi).fillna(False); is_lo = (low == roll_lo).fillna(False)
    sup = pd.Series(np.nan, index=f.index); res = pd.Series(np.nan, index=f.index)
    sup[is_lo] = low[is_lo]; res[is_hi] = high[is_hi]
    sup_lvl = sup.ffill(); res_lvl = res.ffill()
    f["dist_support_atr"] = (close - sup_lvl) / atr
    f["dist_resist_atr"] = (res_lvl - close) / atr
    rng = (high - low).replace(0, np.nan)
    f["wick_reject"] = ((np.maximum(high - np.maximum(close, f["open"]),
                                    np.minimum(close, f["open"]) - low)) / rng).fillna(0.0)
    slope = close.rolling(30).apply(
        lambda w: np.polyfit(np.arange(len(w)), w.to_numpy(float), 1)[0]
        if len(w) == 30 else np.nan, raw=False)
    f["trend_slope_atr"] = slope / atr
    vol = f["volume"] if "volume" in f.columns else pd.Series(1.0, index=f.index)
    f["vol_ratio"] = vol / vol.rolling(20).mean()
    f["ret_1"] = close.pct_change(1); f["ret_4"] = close.pct_change(4)
    f["range_atr"] = rng / atr
    return f
