"""
Risk management engine for position sizing and SL/TP calculation.
Uses ATR-based stops with reward-to-risk ratio enforcement.
Caps SL/TP at HTF support/resistance levels when available.
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


def calc_sl_tp(
    df: pd.DataFrame,
    entry_price: float,
    trend: str = "long",
    atr_mult: float = 1.5,
    min_rrr: float = 2.0,
    atr_col: str = "atr",
    htf_support: Optional[float] = None,
    htf_resistance: Optional[float] = None,
) -> Dict[str, float]:
    """
    Calculate stop-loss and take-profit levels based on ATR.

    For LONG trades:
        SL = entry - (atr_mult * ATR)
        TP = entry + (min_rrr * (entry - SL))

    For SHORT trades:
        SL = entry + (atr_mult * ATR)
        TP = entry - (min_rrr * (SL - entry))

    SL/TP are capped at HTF support/resistance levels when provided:
        - Long SL cannot go below HTF support
        - Short SL cannot go above HTF resistance

    Args:
        df: DataFrame with ATR column (must have rows)
        entry_price: Entry price for the trade
        trend: 'long' or 'short'
        atr_mult: ATR multiplier for stop distance
        min_rrr: Minimum reward-to-risk ratio
        atr_col: Column name for ATR values
        htf_support: HTF support level (cap for long SL)
        htf_resistance: HTF resistance level (cap for short SL)

    Returns:
        Dict with keys: entry, sl, tp, atr, risk, reward, rrr, valid
    """
    # Get the most recent ATR value
    if atr_col not in df.columns or df[atr_col].isna().all():
        raise ValueError(f"ATR column '{atr_col}' not found or all NaN in DataFrame")

    current_atr = df[atr_col].iloc[-1]

    if current_atr <= 0:
        raise ValueError(f"ATR value must be positive, got {current_atr}")

    result = {
        "entry": entry_price,
        "sl": 0.0,
        "tp": 0.0,
        "atr": current_atr,
        "risk": 0.0,
        "reward": 0.0,
        "rrr": 0.0,
        "valid": False,
    }

    if trend == "long":
        # Long: SL below entry
        raw_sl = entry_price - (atr_mult * current_atr)

        # Cap at HTF support (don't go below support)
        if htf_support is not None and raw_sl < htf_support:
            raw_sl = htf_support

        sl = raw_sl
        risk = entry_price - sl
        reward = min_rrr * risk
        tp = entry_price + reward

        # Cap TP at HTF resistance
        if htf_resistance is not None and tp > htf_resistance:
            tp = htf_resistance
            reward = tp - entry_price

    elif trend == "short":
        # Short: SL above entry
        raw_sl = entry_price + (atr_mult * current_atr)

        # Cap at HTF resistance (don't go above resistance)
        if htf_resistance is not None and raw_sl > htf_resistance:
            raw_sl = htf_resistance

        sl = raw_sl
        risk = sl - entry_price
        reward = min_rrr * risk
        tp = entry_price - reward

        # Cap TP at HTF support
        if htf_support is not None and tp < htf_support:
            tp = htf_support
            reward = entry_price - tp

    else:
        raise ValueError(f"Invalid trend '{trend}'. Must be 'long' or 'short'.")

    # Calculate actual RRR
    rrr = reward / risk if risk > 0 else 0.0

    result.update({
        "sl": round(sl, 8),
        "tp": round(tp, 8),
        "risk": round(risk, 8),
        "reward": round(reward, 8),
        "rrr": round(rrr, 2),
        "valid": rrr >= min_rrr and risk > 0,
    })

    return result


def calc_position_size(
    account_balance: float,
    risk_pct: float,
    risk_per_unit: float,
    max_position_pct: float = 25.0,
) -> Dict[str, float]:
    """
    Calculate position size based on risk parameters.

    Position size = (account_balance * risk_pct) / risk_per_unit

    Args:
        account_balance: Total account balance in quote currency
        risk_pct: Percentage of account to risk per trade (e.g., 1.0 = 1%)
        risk_per_unit: Risk per unit (entry - SL) in quote currency
        max_position_pct: Maximum position as % of account balance

    Returns:
        Dict with keys: quantity, cost, risk_amount, risk_pct_actual, valid

    Raises:
        ValueError: If risk_per_unit is not positive
    """
    if risk_per_unit <= 0:
        raise ValueError(f"Risk per unit must be positive, got {risk_per_unit}")

    # Calculate risk amount
    risk_amount = account_balance * (risk_pct / 100.0)

    # Calculate quantity
    quantity = risk_amount / risk_per_unit

    # Calculate cost (assuming entry price = 1 for simplicity; caller multiplies)
    # Actually, we need to calculate cost properly
    # Cost = quantity * entry_price (but entry_price not passed here)
    # We'll return quantity and risk_amount, let caller compute cost

    # Check against max position limit
    risk_pct_actual = (risk_amount / account_balance) * 100.0 if account_balance > 0 else 0.0

    result = {
        "quantity": round(quantity, 8),
        "risk_amount": round(risk_amount, 2),
        "risk_pct_actual": round(risk_pct_actual, 2),
        "valid": risk_pct_actual <= max_position_pct and quantity > 0,
    }

    return result


def validate_rrr(
    entry: float,
    sl: float,
    tp: float,
    min_rrr: float = 2.0,
) -> bool:
    """
    Validate that a trade setup meets minimum reward-to-risk ratio.

    Args:
        entry: Entry price
        sl: Stop loss price
        tp: Take profit price
        min_rrr: Minimum required RRR

    Returns:
        True if RRR >= min_rrr
    """
    risk = abs(entry - sl)
    reward = abs(tp - entry)

    if risk <= 0:
        return False

    rrr = reward / risk
    return rrr >= min_rrr
