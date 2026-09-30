"""Stage 1 data-layer tests (offline — no network access required)."""
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pandas as pd

import data.streamer as streamer
from data.delta_client import DeltaAPIError, DeltaPublicClient, resolve_delta_symbol
from data.quality import candle_staleness_reason, spread_reason, tf_to_seconds


def delta_rows(n=6, tf_sec=900):
    """Candles shaped like the live Delta response: newest first, and the
    bucket for the current (forming) candle present at the top."""
    now = int(time.time())
    now -= now % tf_sec  # aligned bucket start of the forming candle
    rows = []
    for i in range(n):
        t = now - i * tf_sec
        o = 100.0 + i
        rows.append({"time": t, "open": o, "high": o + 1, "low": o - 1,
                     "close": o + 0.5, "volume": 10.0 + i})
    return rows


class DeltaClientTests(unittest.TestCase):
    def setUp(self):
        self.client = DeltaPublicClient("https://delta.invalid", max_rps=1000)

    def test_symbol_mapping(self):
        self.assertEqual(resolve_delta_symbol("BTC/USDT"), "BTCUSD")
        self.assertEqual(resolve_delta_symbol("ETH/USDC"), "ETHUSD")
        self.assertIsNone(resolve_delta_symbol("AAPL"))
        self.assertIsNone(resolve_delta_symbol("EURUSD=X"))
        # Unknown bases may map to a candidate symbol; the product-list check
        # (is_listed) is what keeps non-crypto away from Delta for good.
        self.assertEqual(resolve_delta_symbol("AAPL/USD"), "AAPLUSD")

    def test_unlisted_symbol_filtered_by_product_check(self):
        products = [{"symbol": "BTCUSD", "state": "live",
                     "trading_status": "operational"}]
        with patch.object(DeltaPublicClient, "_get", return_value=products):
            self.assertTrue(self.client.is_listed("BTCUSD"))
            self.assertFalse(self.client.is_listed("AAPLUSD"))

    def test_candles_normalized_and_ordered(self):
        rows = delta_rows(6)
        with patch.object(DeltaPublicClient, "_get", return_value=rows):
            df = self.client.fetch_candles("BTCUSD", "15m", limit=5)
        self.assertEqual(list(df.columns), ["open", "high", "low", "close", "volume"])
        self.assertEqual(df.index.name, "datetime")
        self.assertEqual(str(df.index.tz), "UTC")
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertFalse(df[["open", "high", "low", "close"]].isna().any().any())
        # Raw fetch keeps the forming candle (dropping is confirm_only's job).
        age = (datetime.now(timezone.utc) - df.index[-1]).total_seconds()
        self.assertLess(age, 900)

    def test_is_listed_falls_open_when_products_unavailable(self):
        with patch.object(DeltaPublicClient, "_get",
                          side_effect=DeltaAPIError("down")):
            self.assertTrue(self.client.is_listed("BTCUSD"))

    def test_unsupported_timeframe_raises(self):
        with self.assertRaises(DeltaAPIError):
            self.client.fetch_candles("BTCUSD", "7m", 10)

    def test_network_errors_retry_then_raise(self):
        import requests
        with patch("time.sleep"), patch.object(DeltaPublicClient, "_throttle"):
            with patch.object(requests.Session, "get",
                              side_effect=requests.ConnectionError("down")):
                with self.assertRaises(DeltaAPIError):
                    self.client._get("/v2/tickers/BTCUSD")


class FakeDeltaHistoryServer:
    """Emulates the live /v2/history/candles contract, offline.

    Mirrors the behaviour verified against api.india.delta.exchange on
    2026-09-29: newest-first results, start/end window respected, ``limit``
    honoured, and a hard 4000-bar ceiling per response.
    """

    CEILING = 4000

    def __init__(self, newest_bucket: int, bars: int, tf_sec: int = 900):
        self.newest = newest_bucket
        self.count = bars
        self.tf_sec = tf_sec
        self.calls = 0

    def get(self, path, params=None):
        self.calls += 1
        params = params or {}
        start, end = int(params["start"]), int(params["end"])
        limit = min(int(params["limit"]), self.CEILING)
        oldest = self.newest - self.tf_sec * (self.count - 1)
        times = [t for t in range(self.newest, oldest - 1, -self.tf_sec)
                 if start <= t <= end][:limit]
        return [{"time": t, "open": 100.0, "high": 101.0, "low": 99.0,
                 "close": 100.5, "volume": 5.0} for t in times]


class FetchHistoryPaginationTests(unittest.TestCase):
    """Stage 2 prerequisite: deep history needs paginated candle fetches."""

    TF_SEC = 900

    def setUp(self):
        self.client = DeltaPublicClient("https://delta.invalid", max_rps=1000)
        self.newest = int(time.time())
        self.newest -= self.newest % self.TF_SEC

    def serve(self, bars):
        server = FakeDeltaHistoryServer(self.newest, bars, self.TF_SEC)
        patcher = patch.object(DeltaPublicClient, "_get", side_effect=server.get)
        patcher.start()
        self.addCleanup(patcher.stop)
        return server

    def test_paginates_without_gaps_or_duplicates(self):
        server = self.serve(bars=12000)
        df = self.client.fetch_history("BTCUSD", "15m", total_bars=10000)
        self.assertEqual(len(df), 10000)
        self.assertGreater(server.calls, 1)  # actually did paginate
        self.assertTrue(df.index.is_monotonic_increasing)
        self.assertFalse(df.index.has_duplicates)
        steps = set(df.index.to_series().diff().dropna().dt.total_seconds())
        self.assertEqual(steps, {float(self.TF_SEC)})  # no seam gaps, no overlaps
        self.assertEqual(int(df.index[-1].timestamp()), self.newest)

    def test_short_request_uses_one_page(self):
        server = self.serve(bars=12000)
        df = self.client.fetch_history("BTCUSD", "15m", total_bars=500)
        self.assertEqual(len(df), 500)
        self.assertEqual(server.calls, 1)

    def test_stops_at_beginning_of_history_without_hanging(self):
        server = self.serve(bars=500)
        df = self.client.fetch_history("BTCUSD", "15m", total_bars=10000)
        self.assertEqual(len(df), 500)  # short result, not an error
        steps = set(df.index.to_series().diff().dropna().dt.total_seconds())
        self.assertEqual(steps, {float(self.TF_SEC)})

    def test_end_parameter_bounds_the_window(self):
        self.serve(bars=12000)
        cut = self.newest - self.TF_SEC * 3000
        df = self.client.fetch_history("BTCUSD", "15m", total_bars=1000, end=cut)
        self.assertLessEqual(int(df.index[-1].timestamp()), cut)

    def test_empty_history_returns_empty_frame(self):
        server = self.serve(bars=0)
        df = self.client.fetch_history("BTCUSD", "15m", total_bars=100)
        self.assertTrue(df.empty)
        self.assertEqual(server.calls, 1)

    def test_unsupported_timeframe_raises(self):
        with self.assertRaises(DeltaAPIError):
            self.client.fetch_history("BTCUSD", "7m", total_bars=100)


class QualityTests(unittest.TestCase):
    def frame(self, last_open):
        idx = pd.date_range(end=last_open, periods=5, freq="15min", tz="UTC")
        return pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7.0},
            index=idx,
        )

    def test_tf_to_seconds(self):
        self.assertEqual(tf_to_seconds("15m"), 900)
        self.assertEqual(tf_to_seconds("1h"), 3600)
        self.assertEqual(tf_to_seconds("nonsense"), 900)

    def test_fresh_frame_passes_staleness(self):
        last = datetime.now(timezone.utc) - timedelta(minutes=10)
        self.assertIsNone(candle_staleness_reason(self.frame(last), "15m", 2))

    def test_stale_frame_detected(self):
        last = datetime.now(timezone.utc) - timedelta(hours=2)
        reason = candle_staleness_reason(self.frame(last), "15m", 2)
        self.assertIsNotNone(reason)
        self.assertTrue(reason.startswith("STALE_CANDLES"))

    def test_empty_frame_detected(self):
        self.assertEqual(candle_staleness_reason(pd.DataFrame(), "15m", 2),
                         "EMPTY_FRAME")

    def test_spread_checks(self):
        self.assertIsNone(spread_reason("100.00", "100.05", 0.5))
        self.assertTrue(spread_reason("100.0", "101.0", 0.5).startswith("WIDE_SPREAD"))
        self.assertEqual(spread_reason(None, None), "NO_ORDERBOOK")
        self.assertEqual(spread_reason("101", "100"), "INVALID_ORDERBOOK")


class StreamerRoutingTests(unittest.TestCase):
    def closed_frame(self):
        end = datetime.now(timezone.utc) - timedelta(minutes=20)
        idx = pd.date_range(end=end, periods=4, freq="15min", tz="UTC")
        return pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7.0},
            index=idx,
        )

    def test_delta_preferred_for_crypto(self):
        fake = Mock()
        fake.is_listed.return_value = True
        fake.fetch_candles.return_value = self.closed_frame()
        with patch.object(streamer, "get_delta_client", return_value=fake), \
             patch.object(streamer, "_fetch_yfinance_candles") as yf:
            df = streamer.fetch_recent_candles("BTC/USDT", "15m", 10)
        self.assertEqual(df.attrs["data_source"], "delta")
        yf.assert_not_called()

    def test_falls_back_to_yfinance_when_delta_empty(self):
        fake = Mock()
        fake.is_listed.return_value = True
        fake.fetch_candles.return_value = streamer._empty_frame()
        with patch.object(streamer, "get_delta_client", return_value=fake), \
             patch.object(streamer, "_fetch_yfinance_candles",
                          return_value=self.closed_frame()) as yf:
            df = streamer.fetch_recent_candles("BTC/USDT", "15m", 10)
        self.assertEqual(df.attrs["data_source"], "yahoo")
        yf.assert_called_once()

    def test_stocks_never_touch_delta(self):
        boom = Mock(side_effect=AssertionError("Delta must not be used"))
        with patch.object(streamer, "get_delta_client", boom), \
             patch.object(streamer, "_fetch_yfinance_candles",
                          return_value=self.closed_frame()):
            df = streamer.fetch_recent_candles("AAPL", "15m", 10)
        self.assertEqual(df.attrs["data_source"], "yahoo")

    def test_confirm_only_drops_forming_candle(self):
        end = datetime.now(timezone.utc)  # last candle still forming
        idx = pd.date_range(end=end, periods=4, freq="15min", tz="UTC")
        frame = pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 7.0},
            index=idx,
        )
        fake = Mock()
        fake.is_listed.return_value = True
        fake.fetch_candles.return_value = frame
        with patch.object(streamer, "get_delta_client", return_value=fake):
            df = streamer.fetch_recent_candles("BTC/USDT", "15m", 10,
                                               confirm_only=True)
        self.assertEqual(len(df), 3)


if __name__ == "__main__":
    unittest.main()
