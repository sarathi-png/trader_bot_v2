"""
Technical indicators for signal generation.
Pure pandas/numpy implementations — no external TA library required.
All indicators use rolling windows only — no forward-looking bias.
"""

import pandas as pd
import numpy as np
from typing import Optional


def atr_14(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Average True Range (ATR) over specified period.

    Uses the standard Wilder smoothing method (exponential moving average
    of True Range values).

    Args:
        df: DataFrame with columns [open, high, low, close]
        period: ATR period (default 14)

    Returns:
        pd.Series of ATR values aligned to df index

    Raises:
        ValueError: If required columns are missing from df
    """
    required = {"high", "low", "close"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame must contain columns: {required}")

    # True Range calculation
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()

    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # Wilder smoothing (exponential with alpha = 1/period)
    atr = true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    return atr


def ma_cross(
    df: pd.DataFrame,
    fast_period: int = 9,
    slow_period: int = 21,
    ma_type: str = "sma",
) -> pd.DataFrame:
    """
    Calculate moving averages and crossover signals.

    Args:
        df: DataFrame with 'close' column
        fast_period: Fast MA period
        slow_period: Slow MA period
        ma_type: 'sma' or 'ema'

    Returns:
        DataFrame with added columns:
        - ma_fast: Fast moving average
        - ma_slow: Slow moving average
        - ma_cross_signal: 1 for bullish cross, -1 for bearish, 0 for none
    """
    if "close" not in df.columns:
        raise ValueError("DataFrame must contain 'close' column")

    result = df.copy()

    if ma_type == "ema":
        result["ma_fast"] = result["close"].ewm(span=fast_period, adjust=False).mean()
        result["ma_slow"] = result["close"].ewm(span=slow_period, adjust=False).mean()
    else:  # SMA
        result["ma_fast"] = result["close"].rolling(window=fast_period).mean()
        result["ma_slow"] = result["close"].rolling(window=slow_period).mean()

    # Detect crossover
    fast_above_slow = result["ma_fast"] > result["ma_slow"]
    prev_fast_above = fast_above_slow.shift(1)

    result["ma_cross_signal"] = 0
    result.loc[fast_above_slow & ~prev_fast_above, "ma_cross_signal"] = 1   # Bullish
    result.loc[~fast_above_slow & prev_fast_above, "ma_cross_signal"] = -1  # Bearish

    return result


def rsi(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).

    Args:
        df: DataFrame with 'close' column
        period: RSI period (default 14)

    Returns:
        pd.Series of RSI values (0-100)
    """
    if "close" not in df.columns:
        raise ValueError("DataFrame must contain 'close' column")

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))

    return rsi
