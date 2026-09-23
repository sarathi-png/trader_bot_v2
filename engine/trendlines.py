"""
Trendline analysis using linear regression over swing points.
Fits a line through the last K swing highs or lows to determine
slope and projected trendline value at current bar.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple


def linear_regression_trendline(
    df: pd.DataFrame,
    swing_type: str = "high",
    min_swings: int = 3,
    max_swings: int = 10,
) -> Dict[str, float]:
    """
    Fit a linear regression trendline through recent swing points.

    Uses the last max_swings (or fewer) confirmed swing highs/lows
    to compute a linear trendline: value = slope * index + intercept.

    Args:
        df: DataFrame with columns including swing_high/swing_low boolean
            and the corresponding price column
        swing_type: 'high' for resistance trendline, 'low' for support trendline
        min_swings: Minimum swing points required for valid trendline
        max_swings: Maximum swing points to use (most recent first)

    Returns:
        Dict with keys:
        - slope: Rate of change per bar
        - intercept: Y-intercept
        - current_value: Trendline value at current (last) bar index
        - valid: Whether trendline is valid (enough swings)
        - num_swings: Number of swings used
    """
    result = {
        "slope": 0.0,
        "intercept": 0.0,
        "current_value": 0.0,
        "valid": False,
        "num_swings": 0,
    }

    # Determine swing column and price column
    swing_col = f"swing_{swing_type}"
    price_col = "high" if swing_type == "high" else "low"

    if swing_col not in df.columns or price_col not in df.columns:
        return result

    # Get swing point indices and prices
    swing_mask = df[swing_col] == True  # noqa: E712
    swing_indices = df.index[swing_mask][-max_swings:]  # Last max_swings

    if len(swing_indices) < min_swings:
        return result

    # Get integer positions for regression
    all_indices = df.index.tolist()
    x = np.array([all_indices.index(idx) for idx in swing_indices], dtype=float)
    y = df.loc[swing_indices, price_col].values.astype(float)

    # Linear regression: y = slope * x + intercept
    # Using least squares: slope = cov(x,y) / var(x)
    n = len(x)
    x_mean = np.mean(x)
    y_mean = np.mean(y)

    slope = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
    intercept = y_mean - slope * x_mean

    # Value at current bar (last bar index)
    current_idx = len(df) - 1
    current_value = slope * current_idx + intercept

    result.update({
        "slope": float(slope),
        "intercept": float(intercept),
        "current_value": float(current_value),
        "valid": True,
        "num_swings": int(n),
    })

    return result


def get_trend_direction(
    df: pd.DataFrame,
    n_swings: int = 5,
) -> str:
    """
    Determine overall trend direction from swing point structure.

    Compares the most recent swing highs/lows to determine if the
    market is making higher highs/higher lows (uptrend) or
    lower highs/lower lows (downtrend).

    Args:
        df: DataFrame with swing_high/swing_low columns
        n_swings: Number of recent swings to consider

    Returns:
        'uptrend', 'downtrend', or 'ranging'
    """
    if "swing_high" not in df.columns or "swing_low" not in df.columns:
        return "ranging"

    # Get recent swing highs
    recent_highs = df[df["swing_high"] == True]["high"].tail(n_swings)  # noqa: E712
    recent_lows = df[df["swing_low"] == True]["low"].tail(n_swings)  # noqa: E712

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return "ranging"

    # Check for higher highs and higher lows (uptrend)
    higher_highs = recent_highs.iloc[-1] > recent_highs.iloc[-2]
    higher_lows = recent_lows.iloc[-1] > recent_lows.iloc[-2]

    # Check for lower highs and lower lows (downtrend)
    lower_highs = recent_highs.iloc[-1] < recent_highs.iloc[-2]
    lower_lows = recent_lows.iloc[-1] < recent_lows.iloc[-2]

    if higher_highs and higher_lows:
        return "uptrend"
    elif lower_highs and lower_lows:
        return "downtrend"
    else:
        return "ranging"
