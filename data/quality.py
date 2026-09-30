"""
Data quality gates (Stage 1): candle freshness and orderbook spread sanity.

Every check returns ``None`` when data is acceptable, or a short machine
readable reason string (e.g. ``"STALE_CANDLES:5400s_old"``) that callers log
and persist via the DEGRADED heartbeat so the dashboard always shows why a
scan was skipped instead of silently producing no signal.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pandas as pd

_TF_UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 604800}
_DEFAULT_TF_SECONDS = 900  # mirrors the streamer default of 15m


def tf_to_seconds(timeframe: str) -> int:
    tf = str(timeframe).strip().lower()
    if len(tf) >= 2 and tf[-1] in _TF_UNITS and tf[:-1].isdigit():
        return int(tf[:-1]) * _TF_UNITS[tf[-1]]
    return _DEFAULT_TF_SECONDS


def candle_staleness_reason(df: pd.DataFrame, timeframe: str,
                            max_age_bars: int = 2) -> Optional[str]:
    """Reason string when the newest candle is older than expected.

    ``max_age_bars`` additional full bars of grace are allowed on top of one
    bar interval, so a healthy 15m feed (last candle <= 1 interval old)
    passes until roughly 3 intervals have elapsed with no new bar.
    """
    if df is None or df.empty:
        return "EMPTY_FRAME"
    last_open = df.index[-1]
    if getattr(last_open, "tzinfo", None) is None:
        last_open = last_open.tz_localize("UTC")
    age = (datetime.now(timezone.utc) - last_open).total_seconds()
    limit = (max_age_bars + 1) * tf_to_seconds(timeframe)
    if age > limit:
        return f"STALE_CANDLES:{int(age)}s_old"
    return None


def spread_reason(best_bid, best_ask, max_spread_pct: float = 0.5) -> Optional[str]:
    """Reason string when the top-of-book spread is unusable or too wide."""
    try:
        bid = float(best_bid)
        ask = float(best_ask)
    except (TypeError, ValueError):
        return "NO_ORDERBOOK"
    if bid <= 0 or ask <= 0 or ask < bid:
        return "INVALID_ORDERBOOK"
    mid = (bid + ask) / 2.0
    spread_pct = (ask - bid) / mid * 100.0
    if spread_pct > max_spread_pct:
        return f"WIDE_SPREAD:{spread_pct:.3f}pct"
    return None
