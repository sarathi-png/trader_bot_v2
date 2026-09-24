"""Repeatable v3 unit and integration tests."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import storage
from execution.paper_engine import PaperBroker, RiskError
from operations import next_scan_at
from storage import Store


class V3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.previous = storage._GLOBAL_STORE
        storage._GLOBAL_STORE = Store(Path(self.temp.name) / "test.db")

    def tearDown(self):
        storage._GLOBAL_STORE = self.previous
        self.temp.cleanup()

    def test_dedupe_and_position_limit(self):
        signal = self.signal("one")
        self.assertTrue(storage.get_store().insert_signal(signal))
        self.assertFalse(storage.get_store().insert_signal(signal))
        broker = PaperBroker(0.1, 0.02, 1)
        broker.open_position(signal, 0.1)
        with self.assertRaises(RiskError):
            broker.open_position(self.signal("two"), 0.1)

    def test_paper_exit_includes_fees_and_slippage(self):
        signal = self.signal("exit")
        storage.get_store().insert_signal(signal)
        position = PaperBroker(0.1, 0.02).open_position(signal, 0.1)
        self.assertAlmostEqual(position["entry_price"], 100.02)
        closed = PaperBroker(0.1, 0.02).mark_and_close(position["id"], 110, "TAKE_PROFIT")
        self.assertEqual(closed["status"], "CLOSED")
        self.assertGreater(closed["pnl"], 0)
        self.assertEqual(storage.get_store().recent_signals(1)[0]["status"], "PAPER_CLOSED")

    def test_scheduler_uses_post_close_offset(self):
        target = next_scan_at(datetime(2026, 1, 1, 14, 59, 58, tzinfo=timezone.utc))
        self.assertEqual((target.hour, target.minute, target.second), (15, 0, 5))

    def test_dashboard_snapshot_shape(self):
        store = storage.get_store()
        run = store.start_run(3)
        store.finish_run(run, 3, 0, 0, {"details": []})
        store.set_state("worker_state", "STARTING")
        from operations import dashboard_snapshot
        snapshot = dashboard_snapshot()
        self.assertEqual(len(snapshot["metrics"]), 10)
        self.assertIn("RUNNING", snapshot["health_markdown"])
        self.assertEqual(snapshot["mode"], "PAPER")

    @staticmethod
    def signal(key):
        return {"signal_key": key, "symbol": "TEST", "signal": "BUY", "timeframe": "15m",
                "entry": 100.0, "sl": 95.0, "tp": 110.0, "rrr": 2.0,
                "htf_trend": "uptrend", "source_candle": "2026-01-01T00:00:00+00:00"}


if __name__ == "__main__":
    unittest.main()
