"""
Support and Resistance zone detection using swing point analysis.
Clusters nearby swing points into zones and assigns nearest zone per row.
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Optional


def find_swing_high_low(
    df: pd.DataFrame,
    n: int = 5,
) -> pd.DataFrame:
    """
    Identify swing highs and swing lows using rolling window.

    A swing high at index i requires that:
      df['high'][i] == max(df['high'][i-n:i+n+1])
    Similarly for swing low with df['low'].

    This ensures no forward-looking bias — we only use past AND current data,
    with a symmetric window centered on the current candle.

    Args:
        df: DataFrame with [open, high, low, close] columns
        n: Swing lookback/lookahead window (default 5)

    Returns:
        DataFrame with added boolean columns:
        - swing_high: True at swing high points
        - swing_low: True at swing low points
    """
    required = {"high", "low"}
    if not required.issubset(df.columns):
        raise ValueError(f"DataFrame must contain columns: {required}")

    result = df.copy()

    # Rolling window for highs and lows
    rolling_high = result["high"].rolling(window=2 * n + 1, center=True)
    rolling_low = result["low"].rolling(window=2 * n + 1, center=True)

    # Swing high: current high equals the rolling max
    result["swing_high"] = result["high"] == rolling_high.max()

    # Swing low: current low equals the rolling min
    result["swing_low"] = result["low"] == rolling_low.min()

    # Edge handling: first and last n candles can't be confirmed swings
    result.iloc[:n, result.columns.get_loc("swing_high")] = False
    result.iloc[-n:, result.columns.get_loc("swing_high")] = False
    result.iloc[:n, result.columns.get_loc("swing_low")] = False
    result.iloc[-n:, result.columns.get_loc("swing_low")] = False

    return result


def cluster_zones(
    swing_points: pd.Series,
    prices: pd.Series,
    tolerance_pct: float = 0.003,
) -> List[Tuple[float, float]]:
    """
    Cluster nearby swing points into support/resistance zones.

    Args:
        swing_points: Boolean series where True = swing point at that price level
        prices: Price series corresponding to swing points (e.g., df['high'] for SH)
        tolerance_pct: Clustering tolerance as percentage (default 0.3%)

    Returns:
        List of (zone_low, zone_high) tuples representing clustered zones
    """
    # Extract swing point prices
    swing_prices = prices[swing_points].dropna().values

    if len(swing_prices) == 0:
        return []

    # Sort prices
    sorted_prices = np.sort(swing_prices)

    zones: List[List[float]] = []
    current_cluster = [sorted_prices[0]]

    for i in range(1, len(sorted_prices)):
        # Check if this price is within tolerance of the cluster center
        cluster_center = np.mean(current_cluster)
        pct_diff = abs(sorted_prices[i] - cluster_center) / cluster_center

        if pct_diff <= tolerance_pct:
            current_cluster.append(sorted_prices[i])
        else:
            # Finalize current zone
            zones.append(current_cluster)
            current_cluster = [sorted_prices[i]]

    # Don't forget the last cluster
    zones.append(current_cluster)

    # Convert to (low, high) tuples
    zone_tuples = [(float(np.min(z)), float(np.max(z))) for z in zones]

    return zone_tuples


def find_nearest_zones(
    df: pd.DataFrame,
    n: int = 5,
    tolerance_pct: float = 0.003,
) -> pd.DataFrame:
    """
    For each row, find the nearest support and resistance zone.

    Args:
        df: DataFrame with [open, high, low, close] columns
        n: Swing lookback window
        tolerance_pct: Zone clustering tolerance

    Returns:
        DataFrame with added columns:
        - nearest_support: Nearest support zone high (top of zone below price)
        - nearest_resistance: Nearest resistance zone low (bottom of zone above price)
    """
    # First, identify swing points
    swing_df = find_swing_high_low(df, n=n)

    # Cluster resistance zones (from swing highs)
    res_zones = cluster_zones(
        swing_df["swing_high"],
        swing_df["high"],
        tolerance_pct=tolerance_pct,
    )

    # Cluster support zones (from swing lows)
    sup_zones = cluster_zones(
        swing_df["swing_low"],
        swing_df["low"],
        tolerance_pct=tolerance_pct,
    )

    result = df.copy()

    nearest_sup = []
    nearest_res = []

    for idx in df.index:
        current_price = df.loc[idx, "close"]

        # Find nearest support (highest zone below current price)
        support_val = None
        for zone_low, zone_high in reversed(sup_zones):
            if zone_high < current_price:
                support_val = zone_high
                break
        nearest_sup.append(support_val)

        # Find nearest resistance (lowest zone above current price)
        resistance_val = None
        for zone_low, zone_high in res_zones:
            if zone_low > current_price:
                resistance_val = zone_low
                break
        nearest_res.append(resistance_val)

    result["nearest_support"] = nearest_sup
    result["nearest_resistance"] = nearest_res

    return result
