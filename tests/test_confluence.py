"""Offline tests for Stage 2: confluence scoring, gating, walk-forward simulation."""
import json
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from engine.indicators import atr_14
from engine.confluence import (
    ConfluenceConfig, ConfluenceReport, analyze_confluence, gate_signal,
    zone_component,
)

CFG = ConfluenceConfig(swing_n=2)


def make_frame(closes, volume=100.0, freq="15min", start="2026-01-01", overrides=None):
    """Build an OHLCV frame from closes; overrides patch specific cells by int position."""
    closes = [float(c) for c in closes]
    opens = [closes[0]] + closes[:-1]
    df = pd.DataFrame({
        "open": opens,
        "high": [max(o, c) + 0.1 for o, c in zip(opens, closes)],
        "low": [min(o, c) - 0.1 for o, c in zip(opens, closes)],
        "close": closes,
        "volume": [float(volume)] * len(closes),
    }, index=pd.date_range(start, periods=len(closes), freq=freq, tz="UTC"))
    df.index.name = "datetime"
    for pos, cols in (overrides or {}).items():
        for col, value in cols.items():
            df.iloc[pos, df.columns.get_loc(col)] = value
    return df


def ramp(n=160, start_price=100.0, step=0.35, wobble=0.5):
    t = np.arange(n)
    return start_price + step * t + wobble * np.sin(t / 5.0)


class ConfluenceScoringTests(unittest.TestCase):
    def test_insufficient_data_is_neutral(self):
        report = analyze_confluence(make_frame([100.0] * 10), make_frame([100.0] * 10), CFG)
        self.assertEqual(report.direction, "NEUTRAL")
        self.assertEqual(report.score, 50.0)
        self.assertIn("insufficient data", report.reasons[0])

    def test_uptrend_scores_long(self):
        closes = ramp()
        report = analyze_confluence(make_frame(closes, freq="15min"),
                                    make_frame(closes, freq="1h"), CFG)
        self.assertEqual(report.direction, "LONG")
        self.assertGreater(report.score, 55)
        self.assertGreater(report.components["trend"], 0.3)
        self.assertGreater(report.components["momentum"], 0.0)
        self.assertEqual(len(report.reasons), 4)
        self.assertIsNotNone(report.atr)

    def test_downtrend_scores_short(self):
        closes = ramp(step=-0.35)
        report = analyze_confluence(make_frame(closes, freq="15min"),
                                    make_frame(closes, freq="1h"), CFG)
        self.assertEqual(report.direction, "SHORT")
        self.assertLess(report.score, 45)
        self.assertLess(report.components["trend"], -0.3)

    def test_support_wick_rejection_scores_bullish(self):
        # 80 flat bars; two swing lows cluster a support at 99.0 (bars 20 & 40);
        # final bar dips to 98.8, closes 99.12 -> lower wick 0.32/0.6 = 0.53.
        overrides = {
            20: {"low": 99.0}, 22: {"low": 99.05},
            40: {"low": 99.0}, 42: {"low": 99.05},
            79: {"open": 99.3, "high": 99.4, "low": 98.8, "close": 99.12},
        }
        df = make_frame([100.0] * 80, overrides=overrides)
        atr = float(atr_14(df).iloc[-1])
        comp, reason = zone_component(df, CFG, atr)
        self.assertGreaterEqual(comp, 0.4)
        self.assertIn("rejection", reason)

    def test_broken_support_scores_negative(self):
        overrides = {
            20: {"low": 99.0}, 22: {"low": 99.05},
            40: {"low": 99.0}, 42: {"low": 99.05},
            79: {"open": 99.3, "high": 99.4, "low": 98.4, "close": 98.5},
        }
        df = make_frame([100.0] * 80, overrides=overrides)
        atr = float(atr_14(df).iloc[-1])
        comp, reason = zone_component(df, CFG, atr)
        self.assertLessEqual(comp, -0.4)
        self.assertIn("broken", reason)

    def test_volume_sign_follows_momentum(self):
        closes = ramp()
        ov = {len(closes) - 1: {"volume": 300.0}}
        df = make_frame(closes, overrides=ov)
        report = analyze_confluence(df, make_frame(closes, freq="1h"), CFG)
        self.assertGreater(report.components["volume"], 0.0)


class GateSignalTests(unittest.TestCase):
    def test_aligned_high_score_passes(self):
        ok, note = gate_signal(ConfluenceReport(score=72, direction="LONG"), "BUY", CFG)
        self.assertTrue(ok)
        self.assertIn("ok", note)

    def test_low_side_score_rejected(self):
        ok, note = gate_signal(ConfluenceReport(score=52, direction="LONG"), "BUY", CFG)
        self.assertFalse(ok)
        self.assertIn("LOW_CONFLUENCE", note)

    def test_short_side_score_is_mirrored(self):
        ok, _ = gate_signal(ConfluenceReport(score=30, direction="SHORT"), "SELL", CFG)
        self.assertTrue(ok)  # side score 70 >= 55

    def test_opposite_direction_vetoed(self):
        ok, note = gate_signal(ConfluenceReport(score=80, direction="LONG"), "SELL", CFG)
        self.assertFalse(ok)
        self.assertIn("CONFLUENCE_VETO", note)

    def test_veto_disabled_still_mins_score(self):
        cfg = ConfluenceConfig(swing_n=2, veto_opposite=False, min_score=40)
        ok, _ = gate_signal(ConfluenceReport(score=55, direction="LONG"), "SELL", cfg)
        self.assertTrue(ok)  # no veto; side score 45 >= 40
        ok, note = gate_signal(ConfluenceReport(score=70, direction="LONG"), "SELL", cfg)
        self.assertFalse(ok)  # no veto, but side score 30 < 40
        self.assertIn("LOW_CONFLUENCE", note)

    def test_disabled_gate_always_passes(self):
        cfg = ConfluenceConfig(enabled=False)
        ok, note = gate_signal(ConfluenceReport(score=0, direction="SHORT"), "BUY", cfg)
        self.assertTrue(ok)
        self.assertEqual(note, "confluence disabled")


class SignalPayloadTests(unittest.TestCase):
    def test_to_signal_fields(self):
        report = ConfluenceReport(score=61.5, direction="LONG",
                                  components={"trend": 0.5, "zone": -0.1234},
                                  reasons=["a"])
        fields = report.to_signal_fields()
        self.assertEqual(fields["confluence_score"], 61.5)
        self.assertEqual(fields["confluence_direction"], "LONG")
        self.assertEqual(fields["confluence_components"]["zone"], -0.123)
        self.assertEqual(fields["confluence_reasons"], ["a"])

    def test_signal_row_shows_stored_score(self):
        from operations import signal_row
        row = signal_row({"symbol": "X", "direction": "BUY", "entry": 1, "sl": 2,
                          "tp": 3, "rrr": 2.0, "htf_trend": "uptrend",
                          "status": "NEW", "telegram_status": "SENT",
                          "created_at": "now",
                          "details_json": json.dumps({"confluence_score": 62.0})})
        self.assertEqual(row[6], 62.0)  # Score column, right after RRR

    def test_signal_row_without_score_is_none(self):
        from operations import signal_row
        row = signal_row({"symbol": "X", "details_json": None})
        self.assertIsNone(row[6])


LONG_STUB = ConfluenceReport(score=90.0, direction="LONG", atr=1.0,
                             components={}, reasons=[])
NEUTRAL_STUB = ConfluenceReport(score=50.0, direction="NEUTRAL", atr=1.0,
                                components={}, reasons=[])


def flat_frame(n=300, price=100.0, freq="15min", overrides=None):
    return make_frame([price] * n, freq=freq, overrides=overrides)


class WalkForwardTests(unittest.TestCase):
    """Simulation mechanics with a stubbed decision function (offline, deterministic)."""

    def setUp(self):
        from backtest.walk_forward import BacktestConfig
        self.bt = BacktestConfig(warmup=120, max_hold_bars=48)
        self.ltf = flat_frame(300)
        self.htf = flat_frame(300, freq="1h")

    def test_tp_exit_costs_and_r_multiple(self):
        from backtest.walk_forward import simulate
        ltf = flat_frame(300, overrides={125: {"high": 103.5}})
        with patch("backtest.walk_forward._decide", return_value=LONG_STUB):
            trades = simulate(ltf, self.htf, self.bt, CFG)
        self.assertTrue(trades)
        t = trades[0]
        self.assertEqual(t.side, "LONG")
        self.assertEqual(t.exit_reason, "TAKE_PROFIT")
        self.assertEqual(t.entry_time, ltf.index[121])   # next bar's open
        self.assertAlmostEqual(t.entry, 100.0)
        self.assertAlmostEqual(t.fill_entry, 100.0 * 1.0002)
        self.assertAlmostEqual(t.sl, 98.5)               # close - 1.5 * atr
        self.assertAlmostEqual(t.tp, 103.0)              # +2R
        self.assertAlmostEqual(t.r_multiple, 2.0)
        # Derive costs from the config instead of hard-coding them: the last
        # review found a hard-coded 0.1% here that had silently drifted from
        # the verified Delta taker fee in settings.
        fee_rate = self.bt.fee_pct / 100.0
        slip = self.bt.slippage_pct / 100.0
        self.assertAlmostEqual(t.fill_entry, 100.0 * (1.0 + slip))
        fee_in = t.fill_entry * fee_rate
        fee_out = t.fill_exit * fee_rate
        expected = (t.fill_exit - t.fill_entry - fee_in - fee_out) / t.fill_entry
        self.assertAlmostEqual(t.pnl_pct, expected, places=10)
        self.assertGreater(t.pnl_pct, 0.025)             # ~2.8% net

    def test_ambiguous_bar_exits_at_stop(self):
        from backtest.walk_forward import simulate
        # Bar where BOTH stop and TP are inside the range must resolve stop-first.
        ltf = flat_frame(300, overrides={123: {"high": 103.5, "low": 98.0}})
        with patch("backtest.walk_forward._decide", return_value=LONG_STUB):
            trades = simulate(ltf, self.htf, self.bt, CFG)
        t = trades[0]
        self.assertEqual(t.exit_reason, "STOP_LOSS")
        self.assertAlmostEqual(t.exit_raw, 98.5)
        self.assertAlmostEqual(t.r_multiple, -1.0)

    def test_time_stop_when_neither_level_hits(self):
        from backtest.walk_forward import simulate, BacktestConfig
        bt = BacktestConfig(warmup=120, max_hold_bars=10)
        with patch("backtest.walk_forward._decide", return_value=LONG_STUB):
            trades = simulate(self.ltf, self.htf, bt, CFG)
        t = trades[0]
        self.assertEqual(t.exit_reason, "TIME_STOP")
        self.assertEqual(t.exit_time, self.ltf.index[130])  # scan window i+1 .. i+10

    def test_decisions_never_see_future_candles(self):
        from backtest.walk_forward import simulate
        calls = []

        def spy(ltf_win, htf_win, cfg):
            calls.append((ltf_win.index[-1], htf_win.index.max(), len(ltf_win)))
            return NEUTRAL_STUB

        bt = self.bt
        with patch("backtest.walk_forward._decide", side_effect=spy):
            simulate(self.ltf, self.htf, bt, CFG)
        self.assertGreater(len(calls), 100)
        prev = None
        for ltf_last, htf_max, window in calls:
            self.assertLess(htf_max, ltf_last)      # HTF bars fully closed before decision bar
            self.assertLessEqual(window, bt.window)  # trailing window cap like live
            if prev is not None:
                self.assertGreater(ltf_last, prev)   # single forward scan
            prev = ltf_last

    def test_htf_window_matches_strictly_before_mask(self):
        """searchsorted boundary must equal the original mask semantics."""
        from backtest.walk_forward import simulate
        windows = []

        def spy(ltf_win, htf_win, cfg):
            windows.append((ltf_win.index[-1], htf_win.index.copy()))
            return NEUTRAL_STUB

        with patch("backtest.walk_forward._decide", side_effect=spy):
            simulate(self.ltf, self.htf, self.bt, CFG)
        self.assertGreater(len(windows), 50)
        for ltf_last, htf_index in windows:
            expected = self.htf[self.htf.index < ltf_last].tail(self.bt.window).index
            self.assertTrue(htf_index.equals(expected),
                            f"HTF window drift at {ltf_last}")

    def test_walk_forward_structure(self):
        from backtest.walk_forward import BacktestConfig, walk_forward
        bt = BacktestConfig(warmup=120, max_hold_bars=48, folds=4,
                            threshold_sweep=[50, 60])
        ltf = flat_frame(300, overrides={125: {"high": 103.5}})
        with patch("backtest.walk_forward._decide", return_value=LONG_STUB):
            report = walk_forward(ltf, self.htf, bt, CFG)
        self.assertEqual(len(report.folds), 4)
        self.assertEqual(len(report.thresholds), 2)
        self.assertGreater(report.overall["trades"], 0)
        folded = sum(f["stats"]["trades"] for f in report.folds)
        self.assertEqual(folded, report.overall["trades"])  # every trade in exactly one fold
        self.assertIn("Overall:", report.to_text())


if __name__ == "__main__":
    unittest.main()


