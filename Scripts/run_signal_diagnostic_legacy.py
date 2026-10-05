"""Where (if anywhere) does the confluence score carry predictive content?

avg R across 1409 walk-forward trades was +0.009 — statistically zero — so
the question is no longer "which threshold is best" but "does any component
predict forward returns at all". This measures, per bar, the signed
confluence components against forward returns over several horizons using
rank correlation (information coefficient), plus the mean forward return
conditional on the score's own direction call.

Read-only: it reads the cached history CSV produced by run_walk_forward.py
and changes no state.

Usage: python Scripts/run_signal_diagnostic.py [ltf] [bars]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import numpy as np
import pandas as pd

from data.delta_client import get_delta_client
from engine.confluence import ConfluenceConfig, analyze_confluence

HORIZONS = [4, 16, 48]  # 1h, 4h, 12h on a 15m chart
WINDOW = 200


def load(symbol, timeframe, bars):
    cache = os.path.join(ROOT, "output", f"history_{symbol}_{timeframe}.csv")
    if not os.path.exists(cache):
        print(f"no cache at {cache}; run run_walk_forward.py first")
        sys.exit(1)
    frame = pd.read_csv(cache, index_col=0, parse_dates=True)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.tail(bars)


def spearman(x, y):
    """Rank correlation without a scipy dependency (ties averaged)."""
    mask = ~(np.isnan(x) | np.isnan(y))
    x, y = pd.Series(x[mask]).rank().to_numpy(), pd.Series(y[mask]).rank().to_numpy()
    if len(x) < 30 or x.std() == 0 or y.std() == 0:
        return float("nan"), 0
    return float(np.corrcoef(x, y)[0, 1]), int(len(x))


def main():
    ltf_tf = sys.argv[1] if len(sys.argv) > 1 else "15m"
    bars = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
    htf_tf = "1h"

    df_ltf = load("BTCUSD", ltf_tf, bars)
    df_htf = load("BTCUSD", htf_tf, len(df_ltf) * 4)
    df_ltf, df_htf = df_ltf.iloc[:-1], df_htf.iloc[:-1]
    days = (df_ltf.index[-1] - df_ltf.index[0]).days
    print(f"bars={len(df_ltf)} ({days} days) {df_ltf.index[0]}..{df_ltf.index[-1]}")

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
        row = {"score_signed": report.score - 50.0,
               "direction": report.direction}
        row.update({f"c_{k}": v for k, v in report.components.items()})
        entry = opens[i + 1]
        for h in HORIZONS:
            row[f"fwd_{h}"] = (closes[i + h] - entry) / entry * 100.0
        rows.append(row)

    data = pd.DataFrame(rows)
    print(f"decisions scored: {len(data)}  "
          f"(LONG {int((data.direction == 'LONG').sum())} / "
          f"SHORT {int((data.direction == 'SHORT').sum())} / "
          f"NEUTRAL {int((data.direction == 'NEUTRAL').sum())})")

    print("\nInformation coefficient (Spearman rank corr vs forward return %):")
    header = f"{'predictor':>14}" + "".join(f"{'+' + str(h) + 'b':>9}" for h in HORIZONS)
    print(header + f"{'n':>7}")
    predictors = ["score_signed"] + [f"c_{k}" for k in
                                     ("trend", "zone", "momentum", "volume")]
    for name in predictors:
        cells = []
        for h in HORIZONS:
            ic, count = spearman(data[name].to_numpy(), data[f"fwd_{h}"].to_numpy())
            cells.append(f"{ic:>9.4f}")
        print(f"{name:>14}" + "".join(cells) + f"{count:>7}")

    print("\nForward return (%) conditional on the score's direction call:")
    print(f"{'direction':>10}{'n':>7}" +
          "".join(f"{h}b mean".rjust(11) for h in HORIZONS))
    for label, subset in [("LONG", data[data.direction == "LONG"]),
                          ("SHORT", data[data.direction == "SHORT"]),
                          ("NEUTRAL", data[data.direction == "NEUTRAL"]),
                          ("ALL", data)]:
        cells = "".join(f"{subset[f'fwd_{h}'].mean():>11.3f}" for h in HORIZONS)
        print(f"{label:>10}{len(subset):>7}" + cells)

    print("\nScore deciles vs forward return (signed so LONG/SHORT comparable):")
    signed = data["score_signed"] * data["direction"].map(
        {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0})
    try:
        buckets = pd.qcut(signed, 5, duplicates="drop")
        table = pd.DataFrame({"signed": signed,
                              "fwd": data[f"fwd_{HORIZONS[-1]}"]}).groupby(
                                  buckets, observed=True)["fwd"].agg(["count", "mean"])
        for idx, r in table.iterrows():
            print(f"  {str(idx):>16}  n={int(r['count']):>5}  mean={r['mean']:>7.3f}%")
    except ValueError as exc:
        print(f"  (could not bucket: {exc})")

    out = os.path.join(ROOT, "output", "_signal_diagnostic.log")
    data.to_csv(os.path.join(ROOT, "output", "_signal_diagnostic_rows.csv"),
                index=False)
    print(f"\nrows -> {out}")


if __name__ == "__main__":
    main()