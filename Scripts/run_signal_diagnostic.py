"""Tier-1 diagnostic CLI: HAC-adjusted IC, quantile spreads, DSR, PBO.

Replaces the legacy plain-Spearman diagnostic (kept as
run_signal_diagnostic_legacy.py). Read-only: reads cached history CSVs.

Usage: python Scripts/run_signal_diagnostic.py [ltf] [bars]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd

from engine.confluence import ConfluenceConfig, analyze_confluence
from ml4t.diagnostic import deflated_sharpe, ic_report, pbo_score, quantile_spread

HORIZONS = [4, 16, 48]
WINDOW = 200


def load(symbol, timeframe, bars):
    cache = os.path.join(ROOT, "output", "history_%s_%s.csv" % (symbol, timeframe))
    if not os.path.exists(cache):
        print("no cache at %s; run run_walk_forward.py first" % cache)
        sys.exit(1)
    frame = pd.read_csv(cache, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.tail(bars)


def main():
    ltf_tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
    htf_tf = "1h"
    df_ltf = load("BTCUSD", ltf_tf, bars)
    df_htf = load("BTCUSD", htf_tf, len(df_ltf) * 4)
    df_ltf, df_htf = df_ltf.iloc[:-1], df_htf.iloc[:-1]
    days = (df_ltf.index[-1] - df_ltf.index[0]).days
    print("bars=%d (%d days) %s..%s" % (len(df_ltf), days, df_ltf.index[0], df_ltf.index[-1]))
    cfg = ConfluenceConfig.from_settings()
    opens = df_ltf["open"].to_numpy(float)
    closes = df_ltf["close"].to_numpy(float)
    times = df_ltf.index
    n = len(df_ltf)
    warmup = 200
    htf_pos = np.searchsorted(df_htf.index.asi8, times.asi8, side="left")
    rows = []
    for i in range(warmup, n - max(HORIZONS) - 1):
        report = analyze_confluence(
            df_ltf.iloc[max(0, i - WINDOW + 1): i + 1],
            df_htf.iloc[max(0, int(htf_pos[i]) - WINDOW): int(htf_pos[i])], cfg)
        row = {"score_signed": report.score - 50.0, "direction": report.direction}
        row.update({"c_%s" % k: v for k, v in report.components.items()})
        entry = opens[i + 1]
        for h in HORIZONS:
            row["fwd_%d" % h] = (closes[i + h] - entry) / entry * 100.0
        rows.append(row)
    data = pd.DataFrame(rows)
    print("decisions scored: %d" % len(data))
    predictors = ["score_signed"] + ["c_%s" % k for k in ("trend", "zone", "momentum", "volume")]
    signals = data[predictors]
    forwards = data[["fwd_%d" % h for h in HORIZONS]]
    print("\nInformation coefficient (Spearman IC, HAC t, BH-FDR @10%):")
    print(ic_report(signals, forwards).to_text())
    signed = data["score_signed"] * data["direction"].map(
        {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0})
    print("\nQuantile spreads (top-bottom forward return):")
    for qs in quantile_spread(signed.to_numpy(float), forwards):
        print("  %s spread=%+.3f%% HAC-t=%+.2f (n=%d/%d)" % (
            qs.horizon, qs.spread, qs.spread_hac_t, qs.n_top, qs.n_bottom))
    rets = data["fwd_%d" % HORIZONS[-1]].to_numpy(float) / 100.0
    dsign = data["direction"].map({"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}).to_numpy(float)
    strat = rets * dsign
    dsr = deflated_sharpe(strat[np.isfinite(strat)], trials=len(predictors) * len(HORIZONS))
    print("\nDeflated Sharpe (K=%d): DSR=%.3f SR=%.3f n=%d" % (
        int(dsr["trials"]), dsr["dsr"], dsr["sr"], int(dsr["n"])))
    wide = pd.DataFrame({p: signals[p] * dsign for p in predictors})
    print("PBO (CSCV): %.3f" % pbo_score(wide, n_splits=8)["pbo"])
    out = os.path.join(ROOT, "output", "_signal_diagnostic_rows.csv")
    data.to_csv(out, index=False)
    print("\nrows -> %s" % out)


if __name__ == "__main__":
    main()
