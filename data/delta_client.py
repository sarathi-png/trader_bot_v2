"""
Delta Exchange India public market-data client (Stage 1: data accuracy).

Verified against the live API on 2026-09-29 from this machine:
  - REST base: https://api.india.delta.exchange
  - GET /v2/history/candles?symbol=&resolution=&start=&end=&limit=
      -> {"success": true, "result": [{time, open, high, low, close, volume}, ...]}
         result is NEWEST-FIRST; ``time`` is the candle OPEN time in epoch
         seconds UTC; the currently-forming candle IS included.
  - The per-request response is hard-capped at 4000 bars: asking for 5000,
    10000 or 20000 all return exactly 4000. ``limit`` is therefore honoured
    only up to that ceiling (MAX_CANDLE_LIMIT).
  - ``start``/``end`` paginate cleanly: walking the window backwards from the
    oldest bar of each page produced 13,000 unique bars with zero duplicate
    timestamps and zero missing intervals at the seams.
  - BTCUSD 15m history reaches ~2 years back (a window around 2024-09 is
    populated, 2023 is empty); daily bars reach ~2.8 years.
  - GET /v2/tickers/{symbol}
      -> result.quotes.best_bid / best_ask (strings); result.time (ISO).
  - GET /v2/products
      -> result[*].symbol with state == "live", trading_status == "operational"
  - 12 back-to-back requests caused no HTTP 429, but we still self-throttle
    to DELTA_MAX_RPS (default 5 req/s) to stay under the documented limit.

Public endpoints only — no API keys are used and nothing in this module can
place, cancel, or modify an order.
"""

import logging
import threading
import time
from typing import Dict, Optional, Set

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_OHLCV = ["open", "high", "low", "close", "volume"]

# Timeframes Delta accepts directly (verified live 2026-09-29).
RESOLUTIONS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "1d", "1w"}

_TF_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "8h": 28800,
    "1d": 86400, "1w": 604800,
}

# Bot pairs quoting against a stable coin map to Delta USD-quoted perps.
_CRYPTO_QUOTES = {"USDT", "USD", "USDC", "BUSD", "USDD"}


class DeltaAPIError(RuntimeError):
    """A Delta REST request failed after retries."""


def resolve_delta_symbol(symbol: str) -> Optional[str]:
    """Map a bot symbol to a Delta India perpetual symbol, or None.

    'BTC/USDT' -> 'BTCUSD', 'ETH/USDC' -> 'ETHUSD'. Delta India lists
    USD-quoted coin-margined perps only — stocks ('AAPL') and FX
    ('EURUSD=X') have no Delta product and return None so callers keep
    using yfinance for them.
    """
    if "/" not in symbol:
        return None
    base, _, quote = symbol.partition("/")
    quote = quote.split(":")[0].strip().upper()
    if quote not in _CRYPTO_QUOTES:
        return None
    base = base.strip().upper()
    return f"{base}USD" if base else None


def _empty_frame() -> pd.DataFrame:
    df = pd.DataFrame(columns=_OHLCV)
    df.index = pd.DatetimeIndex([], name="datetime", tz="UTC")
    return df


class DeltaPublicClient:
    """Public-only Delta India REST client with self-throttling and retries."""

    PRODUCTS_TTL = 3600.0
    MAX_CANDLE_LIMIT = 4000  # verified hard per-request ceiling (see module doc)
    HISTORY_PAGE_BARS = 3900  # leave headroom under the ceiling for padding

    def __init__(self, base_url: str, max_rps: float = 5.0,
                 timeout: float = 15.0, session: Optional[requests.Session] = None):
        self.base_url = str(base_url).rstrip("/")
        self.timeout = timeout
        self._min_interval = 1.0 / max(0.5, float(max_rps))
        self._lock = threading.Lock()
        self._last_request = 0.0
        self._session = session or requests.Session()
        self._session.headers.update({
            "User-Agent": "trader-bot-v2/1.0",
            "Accept": "application/json",
        })
        self._symbols: Optional[Set[str]] = None
        self._symbols_expiry = 0.0

    # ─── plumbing ─────────────────────────────────────────────────────────
    def _throttle(self) -> None:
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def _get(self, path: str, params: Optional[dict] = None):
        """GET a public endpoint; return the ``result`` payload.

        Retries network errors, 429 and 5xx with linear backoff (3 attempts),
        then raises DeltaAPIError. Other 4xx responses raise immediately.
        """
        url = self.base_url + path
        last_error = "unknown"
        for attempt in range(3):
            self._throttle()
            try:
                resp = self._session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = f"network error: {exc}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
                time.sleep(1.5 * (attempt + 1))
                continue
            if resp.status_code >= 400:
                raise DeltaAPIError(
                    f"{path} -> HTTP {resp.status_code}: {resp.text[:200]}"
                )
            body = resp.json()
            if not body.get("success", True):
                raise DeltaAPIError(f"{path} -> API error: {str(body)[:200]}")
            return body.get("result")
        raise DeltaAPIError(f"{path} failed after retries ({last_error})")

    # ─── product universe ────────────────────────────────────────────────
    def _product_symbols(self) -> Optional[Set[str]]:
        """Live+operational product symbols, cached for PRODUCTS_TTL.

        Returns None when the endpoint has never been reachable, so callers
        can fall back open rather than block all crypto coverage.
        """
        now = time.time()
        if self._symbols is not None and now < self._symbols_expiry:
            return self._symbols
        try:
            products = self._get("/v2/products") or []
            self._symbols = {
                p["symbol"]
                for p in products
                if p.get("state") == "live"
                and p.get("trading_status") == "operational"
                and p.get("symbol")
            }
            self._symbols_expiry = now + self.PRODUCTS_TTL
        except Exception as exc:
            logger.warning("[Delta] product list unavailable: %s", exc)
            return self._symbols  # stale cache (possibly None)
        return self._symbols

    def is_listed(self, symbol: str) -> bool:
        """True if Delta lists the symbol; falls back open when unknown."""
        symbols = self._product_symbols()
        if not symbols:
            return True
        return symbol in symbols

    # ─── market data ─────────────────────────────────────────────────────
    def fetch_candles(self, symbol: str, timeframe: str = "15m",
                      limit: int = 200) -> pd.DataFrame:
        """Fetch OHLCV candles conforming to the streamer data contract.

        Contract: columns [open, high, low, close, volume] (numeric, no NaN
        in OHLC), index = UTC DatetimeIndex named "datetime", ascending.
        The currently-forming candle (open time + timeframe still in the
        future) IS included, mirroring yfinance behaviour; use
        ``fetch_recent_candles(confirm_only=True)`` to drop it.
        """
        tf = str(timeframe).strip().lower()
        if tf not in RESOLUTIONS:
            raise DeltaAPIError(f"timeframe {timeframe!r} not supported by Delta")
        tf_sec = _TF_SECONDS[tf]
        limit = max(1, min(int(limit), self.MAX_CANDLE_LIMIT))
        end = int(time.time())
        start = end - tf_sec * (limit + 5) * 2
        raw = self._get("/v2/history/candles", {
            "symbol": symbol, "resolution": tf,
            "start": start, "end": end, "limit": limit + 5,
        })
        frame = self._parse_candles(raw)
        return frame.tail(limit)

    def fetch_history(self, symbol: str, timeframe: str = "15m",
                      total_bars: int = 20000, end: Optional[int] = None,
                      max_pages: int = 40) -> pd.DataFrame:
        """Paginate backwards through history to get more than one page.

        The endpoint caps each response at MAX_CANDLE_LIMIT bars, so deep
        history is assembled by walking the [start, end] window backwards:
        each page ends one second before the oldest bar of the previous
        page. Verified live to stitch 13,000 bars with no duplicates and no
        gaps (see module docstring).

        Returns at most ``total_bars`` bars, ascending, ending at ``end``
        (default: now). Stops early when the beginning of history or
        ``max_pages`` is reached, so a short result is not an error.
        """
        tf = str(timeframe).strip().lower()
        if tf not in RESOLUTIONS:
            raise DeltaAPIError(f"timeframe {timeframe!r} not supported by Delta")
        tf_sec = _TF_SECONDS[tf]
        total_bars = max(1, int(total_bars))
        page_bars = min(self.HISTORY_PAGE_BARS, self.MAX_CANDLE_LIMIT - 2)
        cursor = int(end) if end else int(time.time())
        pages: list[pd.DataFrame] = []
        seen = 0
        for _ in range(max(1, int(max_pages))):
            raw = self._get("/v2/history/candles", {
                "symbol": symbol, "resolution": tf,
                "start": cursor - tf_sec * (page_bars + 2),
                "end": cursor,
                "limit": page_bars + 2,
            })
            frame = self._parse_candles(raw)
            if frame.empty:
                break  # walked past the beginning of available history
            pages.append(frame)
            seen += len(frame)
            if seen >= total_bars or len(frame) < page_bars:
                break  # enough data, or the start of history
            cursor = int(frame.index[0].timestamp()) - 1  # index[0] = oldest
        if not pages:
            return _empty_frame()
        # Newest page first: reverse so concat is ascending, then dedupe on
        # the off-by-one overlap that the second-1 cursor can introduce.
        oldest_first = list(reversed(pages))
        frame = pd.concat(oldest_first)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        return frame.tail(total_bars)

    @staticmethod
    def _parse_candles(raw) -> pd.DataFrame:
        """Normalise a candle payload into the streamer data contract."""
        rows = []
        for item in raw or []:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, (list, tuple)) and len(item) >= 6:
                rows.append(dict(zip(
                    ("time", "open", "high", "low", "close", "volume"), item[:6]
                )))
        if not rows:
            return _empty_frame()
        frame = pd.DataFrame(rows)[["time"] + _OHLCV]
        for col in _OHLCV:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        frame["datetime"] = pd.to_datetime(
            frame["time"].astype("int64"), unit="s", utc=True
        )
        frame = (
            frame.sort_values("datetime")
            .drop_duplicates("datetime")
            .set_index("datetime")
        )
        frame.index.name = "datetime"
        return frame[_OHLCV]

    def fetch_quote(self, symbol: str) -> Dict[str, Optional[str]]:
        """Best bid/ask + mark price for spread sanity checks (REST ticker)."""
        result = self._get(f"/v2/tickers/{symbol}") or {}
        quotes = result.get("quotes") or {}
        return {
            "symbol": result.get("symbol", symbol),
            "best_bid": quotes.get("best_bid"),
            "best_ask": quotes.get("best_ask"),
            "mark_price": result.get("mark_price"),
            "ticker_time": result.get("time"),
        }


_CLIENT: Optional[DeltaPublicClient] = None
_CLIENT_LOCK = threading.Lock()


def get_delta_client() -> DeltaPublicClient:
    """Process-wide singleton built from config settings."""
    global _CLIENT
    if _CLIENT is None:
        with _CLIENT_LOCK:
            if _CLIENT is None:
                from config.settings import DELTA_BASE_URL, DELTA_MAX_RPS
                _CLIENT = DeltaPublicClient(DELTA_BASE_URL, max_rps=DELTA_MAX_RPS)
    return _CLIENT

