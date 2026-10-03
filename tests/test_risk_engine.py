"""Unit tests for engine/risk_engine.py.

These pin two real defects found while running the bot against live data:

- HTF resistance sitting barely above entry collapsed the take-profit to
  ~0, so a confluence-70.6 AAPL setup was rejected as "RRR 0.00 < 2.0".
- A zone at or on the wrong side of entry produced a zero or negative stop
  distance, because the cap was applied without checking which side it was on.
"""
import math
import unittest

import pandas as pd

from engine.risk_engine import calc_sl_tp, calc_position_size, validate_rrr


def frame(atr=2.0):
    return pd.DataFrame({"atr": [atr]})


class CalcSlTpTests(unittest.TestCase):
    def test_resistance_just_above_entry_does_not_collapse_target(self):
        """A resistance a cent above entry must not zero out the take-profit."""
        result = calc_sl_tp(
            df=frame(atr=2.0), entry_price=100.0, trend="long",
            atr_mult=1.5, min_rrr=2.0, htf_support=None, htf_resistance=100.01,
        )
        self.assertTrue(result["valid"])
        self.assertGreaterEqual(result["rrr"], 2.0)
        self.assertAlmostEqual(result["tp"], 106.0)   # entry + 2 * (1.5 * atr)
        self.assertAlmostEqual(result["risk"], 3.0)

    def test_stop_on_wrong_side_of_entry_is_ignored(self):
        """Support above entry must never invert or zero the stop."""
        result = calc_sl_tp(
            df=frame(atr=2.0), entry_price=100.0, trend="long",
            atr_mult=1.5, min_rrr=2.0, htf_support=101.0, htf_resistance=None,
        )
        self.assertGreater(result["risk"], 0)
        self.assertLess(result["sl"], 100.0)
        self.assertTrue(result["valid"])

    def test_resistance_on_wrong_side_of_entry_is_ignored(self):
        """Resistance below entry must not become the short's stop."""
        result = calc_sl_tp(
            df=frame(atr=2.0), entry_price=100.0, trend="short",
            atr_mult=1.5, min_rrr=2.0, htf_support=None, htf_resistance=99.0,
        )
        self.assertGreater(result["risk"], 0)
        self.assertGreater(result["sl"], 100.0)
        self.assertTrue(result["valid"])

    def test_nan_levels_are_treated_as_absent(self):
        """A NaN zone must not leak into sl/tp, because NaN is not None."""
        nan = float("nan")
        result = calc_sl_tp(
            df=frame(atr=2.0), entry_price=100.0, trend="long",
            atr_mult=1.5, min_rrr=2.0, htf_support=nan, htf_resistance=nan,
        )
        for key in ("sl", "tp", "risk", "reward", "rrr"):
            self.assertTrue(math.isfinite(result[key]), f"{key} was {result[key]!r}")
        self.assertTrue(result["valid"])

    def test_valid_support_cap_still_tightens_the_long_stop(self):
        """The intended behaviour survives: support tightens a below-entry stop."""
        result = calc_sl_tp(
            df=frame(atr=2.0), entry_price=100.0, trend="long",
            atr_mult=1.5, min_rrr=2.0, htf_support=98.5, htf_resistance=None,
        )
        self.assertAlmostEqual(result["sl"], 98.5)
        self.assertAlmostEqual(result["risk"], 1.5)
        self.assertTrue(result["valid"])

    def test_non_positive_atr_is_rejected(self):
        with self.assertRaises(ValueError):
            calc_sl_tp(df=frame(atr=0.0), entry_price=100.0, trend="long")

    def test_invalid_trend_is_rejected(self):
        with self.assertRaises(ValueError):
            calc_sl_tp(df=frame(atr=2.0), entry_price=100.0, trend="sideways")


class PositionSizeTests(unittest.TestCase):
    def test_risk_per_unit_must_be_positive(self):
        with self.assertRaises(ValueError):
            calc_position_size(10_000.0, 1.0, 0.0)

    def test_size_follows_account_risk(self):
        size = calc_position_size(10_000.0, 1.0, 5.0)
        self.assertAlmostEqual(size["quantity"], 20.0)
        self.assertTrue(size["valid"])


class ValidateRrrTests(unittest.TestCase):
    def test_zero_risk_fails_validation(self):
        self.assertFalse(validate_rrr(100.0, 100.0, 120.0, min_rrr=2.0))

    def test_two_to_one_passes(self):
        self.assertTrue(validate_rrr(100.0, 98.0, 104.0, min_rrr=2.0))


if __name__ == "__main__":
    unittest.main()