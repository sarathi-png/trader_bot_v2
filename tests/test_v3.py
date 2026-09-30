"""Repeatable v3 unit and integration tests."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import storage
from execution.paper_engine import PaperBroker, RiskError
from operations import format_display_time, next_scan_at
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

    def test_display_time_format(self):
        value = datetime(2026, 9, 24, 21, 5, tzinfo=timezone.utc)
        self.assertEqual(format_display_time(value), "2026-09-24:9.05 PM UTC")
        midnight = datetime(2026, 9, 24, 0, 5, tzinfo=timezone.utc)
        self.assertEqual(format_display_time(midnight), "2026-09-24:12.05 AM UTC")

    def test_dashboard_snapshot_shape(self):
        store = storage.get_store()
        run = store.start_run(3)
        store.finish_run(run, 3, 0, 0, {"details": []})
        store.set_state("worker_state", "STARTING")
        from operations import dashboard_snapshot
        snapshot = dashboard_snapshot()
        self.assertEqual(len(snapshot["metrics"]), 13)  # Stage 4 gate row + paper track record
        self.assertIn("RUNNING", snapshot["health_markdown"])
        self.assertEqual(snapshot["mode"], "PAPER")
        from operations import risk_snapshot
        risk = risk_snapshot()
        self.assertEqual(risk["execution_mode"], "PAPER")
        self.assertIn("live_allowed", risk)

    def test_dashboard_builds_without_error(self):
        """Regression: app.py must build its Blocks and wire every event.

        A gr.DataFrame has no .click() event in Gradio 6, and binding one
        crashed the Space at import time. Building the Blocks catches that
        whole class of error without launching a server.
        """
        try:
            import spaces  # noqa: F401  # provided by the HF Spaces runtime
        except ImportError:
            self.skipTest("spaces package not installed (HF Spaces runtime only)")
        import app
        self.assertGreaterEqual(len(app.demo.fns), 6)
        keys = [row[0] for row in app.mode_rows()]
        self.assertIn("effective_mode", keys)
        self.assertIn("kill_switch", keys)
        self.assertIn("live_gate_reason", keys)

    def test_dashboard_allows_serving_charts(self):
        """Regression: charts live outside the app dir, so Gradio needs allowed_paths.

        On a Space CHART_DIR is /data/charts. Without this, every page load
        raises "Cannot move ... to the gradio cache dir" as soon as a chart
        exists, which blanks the whole dashboard.
        """
        import app
        from config.settings import CHART_DIR
        self.assertIn(str(CHART_DIR), app.ALLOWED_PATHS)

    def test_dashboard_can_release_kill_switch(self):
        """The kill switch must be releasable from the dashboard, not only engageable."""
        import app
        from execution.modes import confirmation_phrase, engage_kill_switch, kill_switch_active
        engage_kill_switch("unit test")
        self.assertTrue(kill_switch_active())
        msg, _ = app.release_kill("wrong phrase")
        self.assertIn("Incorrect", msg)
        self.assertTrue(kill_switch_active())
        msg, _ = app.release_kill(confirmation_phrase())
        self.assertFalse(kill_switch_active())

    def test_scan_cycle_reconciles_paper_exits(self):
        """Regression: the headless loop must close positions, not only open them."""
        import main
        with patch.object(main, "run_analysis_once", return_value=[{"s": 1}]), \
             patch("operations.monitor_paper_positions", return_value=[{"c": 1}]) as monitor:
            signals, closed = main.run_scan_cycle()
        self.assertEqual(len(signals), 1)
        self.assertEqual(len(closed), 1)
        monitor.assert_called_once()

    def test_paper_exit_detects_intrabar_stop(self):
        """An intrabar stop touch closes the trade even if the bar closes above it."""
        signal = self.signal("intrabar")
        storage.get_store().insert_signal(signal)
        PaperBroker(0.0, 0.0).open_position(signal, 1.0)  # BUY: sl=95, tp=110
        closed = PaperBroker(0.0, 0.0).check_exit(
            {"TEST": {"high": 104.0, "low": 94.0, "close": 103.0}})
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "STOP_LOSS")
        self.assertEqual(closed[0]["exit_price"], 95.0)

    def test_paper_exit_is_stop_first_when_bar_touches_both(self):
        """A bar spanning both levels resolves to the stop, as in the backtest."""
        signal = self.signal("both")
        storage.get_store().insert_signal(signal)
        PaperBroker(0.0, 0.0).open_position(signal, 1.0)
        closed = PaperBroker(0.0, 0.0).check_exit(
            {"TEST": {"high": 111.0, "low": 94.0, "close": 105.0}})
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["exit_reason"], "STOP_LOSS")

    def test_paper_exit_holds_when_levels_untouched(self):
        signal = self.signal("hold")
        storage.get_store().insert_signal(signal)
        PaperBroker(0.0, 0.0).open_position(signal, 1.0)
        closed = PaperBroker(0.0, 0.0).check_exit(
            {"TEST": {"high": 101.0, "low": 99.0, "close": 100.5}})
        self.assertEqual(closed, [])

    @staticmethod
    def signal(key):
        return {"signal_key": key, "symbol": "TEST", "signal": "BUY", "timeframe": "15m",
                "entry": 100.0, "sl": 95.0, "tp": 110.0, "rrr": 2.0,
                "htf_trend": "uptrend", "source_candle": "2026-01-01T00:00:00+00:00"}


if __name__ == "__main__":
    unittest.main()
