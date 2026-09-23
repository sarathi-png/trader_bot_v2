"""
Market data streaming and candle fetching.
Uses CCXT for exchange data with yfinance fallback for stocks/forex.
"""

import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from typing import Optional, Literal

# Exchange instance (lazy init)
_exchange: Optional[ccxt.Exchange] = None


def _get_exchange(exchange_name: str = "binance") -> ccxt.Exchange:
    """Get or create a CCXT exchange instance."""
    global _exchange
    if _exchange is None or _exchange.id != exchange_name:
        exchange_class = getattr(ccxt, exchange_name, None)
        if exchange_class is None:
            raise ValueError(f"Exchange '{exchange_name}' not supported by CCXT")
        _exchange = exchange_class({"enableRateLimit": True})
    return _exchange


def fetch_recent_candles(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
    exchange_name: str = "binance",
) -> pd.DataFrame:
    """
    Fetch recent OHLCV candles for a given symbol.

    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT', 'AAPL', 'EURUSD=X')
        timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        limit: Number of candles to fetch (default 200)
        exchange_name: CCXT exchange identifier

    Returns:
        DataFrame with columns [open, high, low, close, volume] and datetime index

    Note:
        For stocks/forex on CCXT, the symbol format may differ by exchange.
        Binance supports crypto directly. For AAPL/EURUSD, consider yfinance
        as a fallback (see commented implementation below).
    """
    try:
        exchange = _get_exchange(exchange_name)

        # Fetch OHLCV data
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)

        if not ohlcv:
            raise ValueError(f"No data returned for {symbol} on {timeframe}")

        # Convert to DataFrame
        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )

        # Convert timestamp to datetime and set as index
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)

        # Ensure numeric types
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Drop any rows with NaN values
        df.dropna(inplace=True)

        return df

    except Exception as e:
        print(f"[Streamer] Error fetching {symbol} {timeframe}: {e}")
        # Return empty DataFrame on error
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])


# ─── yfinance Fallback (for stocks/forex) ───────────────────────────────────
# Uncomment and use if CCXT doesn't support your asset class:

# def fetch_recent_candles_yfinance(
#     symbol: str,
#     timeframe: str = "15m",
#     limit: int = 200,
# ) -> pd.DataFrame:
#     """
#     Fetch candles using yfinance (alternative to CCXT).
#     Better for stocks and forex on some exchanges.
#     """
#     import yfinance as yf
#
#     # Map timeframe to yfinance interval
#     tf_map = {
#         "1m": "1m", "5m": "5m", "15m": "15m",
#         "30m": "30m", "1h": "1h", "1d": "1d",
#     }
#     interval = tf_map.get(timeframe, "15m")
#
#     # Calculate period based on limit and timeframe
#     # yfinance limits intraday data to 7 days for 1m/5m/15m
#     ticker = yf.Ticker(symbol)
#     df = ticker.history(period="7d", interval=interval)
#
#     if df.empty:
#         return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
#
#     # Standardize column names
#     df.columns = [c.lower() for c in df.columns]
#     df = df[["open", "high", "low", "close", "volume"]].tail(limit)
#
#     return df
