"""
Market data streaming and candle fetching.

Primary source: yfinance for every symbol (crypto, stocks, forex).
HuggingFace Spaces blocks Binance with HTTP 451 in the hosting region,
so the CCXT path is only an optional fallback used when the configured
exchange is a real CCXT exchange and yfinance failed.

Contract for every returned frame:
    - columns: [open, high, low, close, volume] (numeric)
    - index:   UTC DatetimeIndex named "datetime"
    - no NaN rows in OHLC columns
"""

import logging
import math
from typing import Optional

import pandas as pd

import ccxt

logger = logging.getLogger(__name__)

# Exchange instance (lazy init, only used by the CCXT fallback path)
_exchange: Optional[ccxt.Exchange] = None

_OHLCV = ["open", "high", "low", "close", "volume"]

# Intervals yfinance serves directly ("1w" is accepted as input, mapped to "1wk").
_YF_DIRECT = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk"}

# Yahoo's maximum lookback per interval, in days. Requesting more fails.
_YF_MAX_DAYS = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 730}

# yfinance `period` values that the Yahoo chart API accepts, ascending.
_PERIOD_LADDER = [
    (1, "1d"),
    (5, "5d"),
    (30, "1mo"),
    (90, "3mo"),
    (180, "6mo"),
    (365, "1y"),
    (730, "2y"),
    (1825, "5y"),
    (3650, "10y"),
]


def _empty_frame() -> pd.DataFrame:
    """Contract-conforming empty result."""
    df = pd.DataFrame(columns=_OHLCV)
    df.index = pd.DatetimeIndex([], name="datetime", tz="UTC")
    return df


def _get_exchange(exchange_name: str = "binance") -> ccxt.Exchange:
    """Get or create a CCXT exchange instance (fallback path only)."""
    global _exchange
    if _exchange is None or _exchange.id != exchange_name:
        exchange_class = getattr(ccxt, exchange_name, None)
        if exchange_class is None:
            raise ValueError(f"Exchange '{exchange_name}' not supported by CCXT")
        _exchange = exchange_class({"enableRateLimit": True})
    return _exchange


def _to_yfinance_symbol(symbol: str) -> str:
    """Map CCXT-style symbols to Yahoo Finance tickers.

    'BTC/USDT' -> 'BTC-USD', 'ETH/USDT' -> 'ETH-USD', 'BTC/EUR' -> 'BTC-EUR'.
    Symbols without '/' (e.g. 'AAPL', 'EURUSD=X') pass through unchanged.
    """
    if "/" not in symbol:
        return symbol
    base, _, quote = symbol.partition("/")
    quote = quote.split(":")[0]  # strip collateral suffixes if present
    quote = {"USDT": "USD", "USDC": "USD", "BUSD": "USD"}.get(quote.upper(), quote)
    return f"{base}-{quote}"


def _hours_per_bar(timeframe: str) -> float:
    """Approximate wall-clock hours covered by one bar of `timeframe`."""
    tf = timeframe.strip().lower()
    try:
        if tf.endswith("m"):
            return int(tf[:-1]) / 60.0
        if tf.endswith("h"):
            return float(tf[:-1])
        if tf.endswith("d"):
            return float(tf[:-1]) * 24.0
        if tf.endswith("w"):
            return float(tf[:-1]) * 168.0
    except ValueError:
        pass
    return 0.25


def _resolve_interval(timeframe: str):
    """Return (fetch_interval, resample_rule, hours_per_bar).

    resample_rule is None when yfinance serves the timeframe directly;
    otherwise the base interval is fetched and aggregated up (e.g. 4h from 1h).
    """
    tf = timeframe.strip().lower()
    if tf == "1w":
        return "1wk", None, 168.0
    if tf in _YF_DIRECT:
        return tf, None, _hours_per_bar(tf)
    if tf.endswith("h") and tf[:-1].isdigit() and int(tf[:-1]) >= 1:
        n = int(tf[:-1])
        if n == 1:
            return "1h", None, 1.0
        return "1h", f"{n}h", float(n)
    logger.warning("[Streamer] Unsupported timeframe %r, using 15m", timeframe)
    return "15m", None, 0.25

def _period_for(fetch_interval: str, hours_per_bar: float, limit: int) -> str:
    """Pick the smallest valid yfinance period covering `limit` bars,
    without exceeding Yahoo's per-interval lookback cap."""
    days_needed = math.ceil(limit * hours_per_bar / 24.0) + 7
    cap = _YF_MAX_DAYS.get(fetch_interval, 3650)
    allowed = [(d, p) for d, p in _PERIOD_LADDER if d <= cap] or _PERIOD_LADDER[:1]
    for days, period in allowed:
        if days >= days_needed:
            return period
    return allowed[-1][1]


def _normalize_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Lowercase columns, UTC datetime index, numeric dtypes, drop NaN OHLC."""
    df = raw.copy()
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    if "volume" not in df.columns:
        df["volume"] = 0.0
    missing = [c for c in _OHLCV if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df = df[_OHLCV].copy()

    df.index = pd.to_datetime(df.index)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    df.index.name = "datetime"

    for col in _OHLCV:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["volume"] = df["volume"].fillna(0.0)
    df.dropna(subset=["open", "high", "low", "close"], inplace=True)
    return df

def _fetch_yfinance_candles(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
) -> pd.DataFrame:
    """Fetch OHLCV candles from Yahoo Finance (primary data source)."""
    try:
        import yfinance as yf
    except ImportError:
        logger.warning("[Streamer] yfinance is not installed")
        return _empty_frame()

    fetch_interval, resample_rule, hours_per_bar = _resolve_interval(timeframe)
    yf_symbol = _to_yfinance_symbol(symbol)
    period = _period_for(fetch_interval, hours_per_bar, limit)

    try:
        raw = yf.Ticker(yf_symbol).history(period=period, interval=fetch_interval)
    except Exception as exc:
        logger.warning(
            "[Streamer] yfinance error for %s (%s, %s): %s",
            yf_symbol, period, fetch_interval, exc,
        )
        return _empty_frame()

    if raw is None or raw.empty:
        logger.info(
            "[Streamer] yfinance returned no rows for %s (%s, %s)",
            yf_symbol, period, fetch_interval,
        )
        return _empty_frame()

    try:
        df = _normalize_frame(raw)
    except Exception as exc:
        logger.warning("[Streamer] bad yfinance data for %s: %s", yf_symbol, exc)
        return _empty_frame()

    if resample_rule is not None and not df.empty:
        df = (
            df.resample(resample_rule)
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna(subset=["open", "high", "low", "close"])
        )

    return df.tail(limit)


def _fetch_ccxt_candles(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
    exchange_name: str = "binance",
) -> pd.DataFrame:
    """Fetch OHLCV candles via CCXT (fallback path; Binance is 451 on HF)."""
    try:
        exchange = _get_exchange(exchange_name)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not ohlcv:
            raise ValueError(f"No data returned for {symbol} on {timeframe}")

        df = pd.DataFrame(
            ohlcv,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.set_index("timestamp", inplace=True)
        df.index.name = "datetime"

        for col in _OHLCV:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df.dropna(inplace=True)
        return df[_OHLCV].tail(limit)

    except Exception as exc:
        logger.warning(
            "[Streamer] CCXT fetch failed for %s %s on %s: %s",
            symbol, timeframe, exchange_name, exc,
        )
        return _empty_frame()


def fetch_recent_candles(
    symbol: str,
    timeframe: str = "15m",
    limit: int = 200,
    exchange_name: str = "yahoo",
) -> pd.DataFrame:
    """Fetch recent OHLCV candles for a given symbol.

    yfinance is tried first for every symbol, crypto included: it works
    from HuggingFace Spaces where Binance answers HTTP 451. When
    yfinance fails and `exchange_name` is a real CCXT exchange, the
    CCXT path is used as a fallback.

    Args:
        symbol: Trading pair symbol (e.g. 'BTC/USDT', 'AAPL', 'EURUSD=X')
        timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d')
        limit: Number of candles to fetch (default 200)
        exchange_name: Data source hint; 'yahoo' disables the CCXT fallback

    Returns:
        DataFrame with [open, high, low, close, volume] and a UTC
        DatetimeIndex named "datetime"; empty frame on total failure.
    """
    df = _fetch_yfinance_candles(symbol, timeframe, limit)
    if not df.empty:
        return df

    if str(exchange_name).lower() in ("yahoo", "yfinance", "yf"):
        return _empty_frame()

    logger.info("[Streamer] Falling back to CCXT (%s) for %s", exchange_name, symbol)
    return _fetch_ccxt_candles(symbol, timeframe, limit, exchange_name)


