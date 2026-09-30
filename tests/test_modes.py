"""Offline tests for Stage 4: execution modes, LIVE evidence gate, kill switch."""
import tempfile
import unittest
from pathlib import Path

import storage
from execution.modes import (
    ExecutionMode, confirmation_phrase, configured_mode, effective_mode,
    engage_kill_switch, kill_switch_active, release_kill_switch,
)
from storage import Store


class ModeTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.previous = storage._GLOBAL_STORE
        storage._GLOBAL_STORE = Store(Path(self.temp.name) / "modes.db")
        self.store = storage.get_store()

    def tearDown(self):
        storage._GLOBAL_STORE = self.previous
        self.temp.cleanup()

    def record_closed(self, pnls):
        """Insert closed paper positions carrying the given P&L values.

        Written as ONE bulk transaction: the evidence-gate tests need a
        few hundred rows, and inserting them one at a time held the
        SQLite write lock long enough to stall the suite.
        """
        rows = [(f"k{i}", "BTC/USDT", "BUY", 100.0, 0.01, 95.0, 110.0, 0.0, pnl)
                for i, pnl in enumerate(pnls)]
        with self.store._tx() as c:
            c.executemany(
                "INSERT INTO positions(signal_key,created_at,symbol,side,entry_price,"
                "quantity,sl,tp,entry_fee,status,exit_price,exit_reason,pnl,closed_at)"
                " VALUES (?,datetime('now'),?,?,?,?,?,?,?,'CLOSED',100.0,'TEST',?,"
                "datetime('now'))", rows)


class ModeParsingTests(ModeTestBase):
    def test_parse_known_modes(self):
        for value in ("manual", "PAPER", " Live "):
            self.assertIn(ExecutionMode.parse(value), tuple(ExecutionMode))

    def test_unknown_mode_falls_back_to_paper(self):
        self.assertIs(ExecutionMode.parse("banana"), ExecutionMode.PAPER)
        self.assertIs(ExecutionMode.parse(None), ExecutionMode.PAPER)

    def test_default_mode_is_paper(self):
        self.assertIs(configured_mode(), ExecutionMode.PAPER)
        self.assertIs(effective_mode(), ExecutionMode.PAPER)


class KillSwitchTests(ModeTestBase):
    def test_kill_switch_forces_paper_immediately(self):
        self.store.set_state("execution_mode", ExecutionMode.LIVE.value)
        self.assertIs(configured_mode(), ExecutionMode.LIVE)
        result = engage_kill_switch("unit test")
        self.assertTrue(result["kill_switch"])
        self.assertIs(effective_mode(), ExecutionMode.PAPER)
        self.assertIs(configured_mode(), ExecutionMode.PAPER)

    def test_kill_switch_persists_across_new_store_instance(self):
        engage_kill_switch("unit test")
        self.assertEqual(Store(self.store.path).get_state("kill_switch"), "true")

    def test_release_requires_phrase(self):
        engage_kill_switch("unit test")
        ok, _ = release_kill_switch("nope")
        self.assertFalse(ok)
        self.assertTrue(kill_switch_active())
        ok, _ = release_kill_switch(confirmation_phrase())
        self.assertTrue(ok)
        self.assertFalse(kill_switch_active())


class LiveEvidenceGateTests(ModeTestBase):
    def test_empty_history_blocks_live(self):
        from operations import live_gate_report
        allowed, reason = live_gate_report()
        self.assertFalse(allowed)
        self.assertIn("paper trades recorded", reason)

    def test_thin_sample_blocks_live(self):
        from operations import live_gate_report
        self.record_closed([10.0] * 5)  # 5 trades, all winners
        allowed, reason = live_gate_report()
        self.assertFalse(allowed)
        self.assertIn("paper trades recorded", reason)

    def test_low_win_rate_blocks_live(self):
        from operations import live_gate_report
        # 210 trades but only 30% winners: sample size fine, quality is not
        self.record_closed([5.0] * 63 + [-5.0] * 147)
        allowed, reason = live_gate_report()
        self.assertFalse(allowed)
        self.assertIn("win rate", reason)

    def test_negative_expectancy_blocks_live(self):
        from operations import live_gate_report
        # 54.5% win rate, but winners too small to cover the losers
        self.record_closed([1.0] * 120 + [-3.0] * 100)
        allowed, reason = live_gate_report()
        self.assertFalse(allowed)
        self.assertIn("breakeven", reason)

    def test_solid_history_unlocks_live(self):
        from operations import live_gate_report
        self.record_closed([10.0] * 130 + [-5.0] * 80)  # 210 trades, 61.9% win
        allowed, reason = live_gate_report()
        self.assertTrue(allowed, reason)

    def test_kill_switch_blocks_live_even_with_good_history(self):
        from operations import live_gate_report
        self.record_closed([10.0] * 130 + [-5.0] * 80)
        engage_kill_switch("unit test")
        allowed, reason = live_gate_report()
        self.assertFalse(allowed)
        self.assertIn("kill switch", reason)


class ModeChangeTests(ModeTestBase):
    def test_live_requires_confirmation_phrase(self):
        from operations import request_mode_change
        self.record_closed([10.0] * 130 + [-5.0] * 80)  # would otherwise qualify
        ok, msg = request_mode_change("LIVE", "let me in")
        self.assertFalse(ok)
        self.assertIn("confirmation phrase", msg)
        self.assertIs(configured_mode(), ExecutionMode.PAPER)

    def test_live_with_phrase_still_blocked_by_poor_history(self):
        from operations import request_mode_change
        ok, msg = request_mode_change("LIVE", confirmation_phrase())
        self.assertFalse(ok)
        self.assertIn("paper trades recorded", msg)
        self.assertIs(configured_mode(), ExecutionMode.PAPER)

    def test_live_accepted_only_with_phrase_and_history(self):
        from operations import request_mode_change
        self.record_closed([10.0] * 130 + [-5.0] * 80)
        ok, msg = request_mode_change("LIVE", confirmation_phrase())
        self.assertTrue(ok, msg)
        self.assertIs(effective_mode(), ExecutionMode.LIVE)

    def test_manual_and_paper_always_allowed(self):
        from operations import request_mode_change
        for mode in ("MANUAL", "PAPER"):
            ok, _ = request_mode_change(mode)
            self.assertTrue(ok)
            self.assertIs(configured_mode(), ExecutionMode.parse(mode))

    def test_kill_switch_blocks_non_paper_mode_change(self):
        from operations import request_mode_change
        engage_kill_switch("unit test")
        ok, msg = request_mode_change("MANUAL")
        self.assertFalse(ok)
        self.assertIn("Kill switch", msg)


class PreOrderGateTests(ModeTestBase):
    def test_manual_mode_refuses_positions(self):
        from operations import can_open_position, request_mode_change
        request_mode_change("MANUAL")
        allowed, reason = can_open_position()
        self.assertFalse(allowed)
        self.assertIn("MANUAL", reason)

    def test_kill_switch_refuses_positions(self):
        from operations import can_open_position
        engage_kill_switch("unit test")
        allowed, reason = can_open_position()
        self.assertFalse(allowed)
        self.assertIn("Kill switch", reason)

    def test_paper_mode_allows_position(self):
        from operations import can_open_position
        allowed, reason = can_open_position()
        self.assertTrue(allowed, reason)
        self.assertIn("PAPER", reason)

    def test_daily_loss_limit_blocks(self):
        from operations import can_open_position
        with self.store._tx() as c:
            c.execute("INSERT INTO daily_risk(day,realized_pnl) VALUES(date('now'),-99999) "
                      "ON CONFLICT(day) DO UPDATE SET realized_pnl=-99999")
        allowed, reason = can_open_position()
        self.assertFalse(allowed)
        self.assertIn("loss limit", reason)

    def test_open_position_limit_blocks(self):
        from config import settings
        from operations import can_open_position
        for i in range(settings.MAX_OPEN_POSITIONS):
            self.store.open_position({"signal_key": f"p{i}", "symbol": "BTC/USDT"},
                                     "BUY", 100.0, 0.01, 95.0, 110.0, 0.0, "TEST")
        allowed, reason = can_open_position()
        self.assertFalse(allowed)
        self.assertIn("limit reached", reason)


if __name__ == "__main__":
    unittest.main()
