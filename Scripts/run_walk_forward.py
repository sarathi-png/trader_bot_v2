"""Live walk-forward check: real Delta BTCUSD candles through the Stage 2 gate.

Usage: python Scripts/run_walk_forward.py [ltf] [htf] [bars] [--fresh]
Pulls deep history from Delta India public REST (no keys, read-only) via
paginated fetch_history, simulates the confluence gate with paper-engine
costs, and prints per-fold and per-threshold stats.

History is cached under output/ so repeated runs are reproducible and do not
re-download; pass --fresh to force a re-pull. Report goes to
output/_walk_forward.log.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import pandas as pd

from backtest.walk_forward import BacktestConfig, walk_forward
from data.delta_client import get_delta_client


def load_history(client, symbol, timeframe, bars, fresh=False):
    """Paginated history, cached as CSV so a re-run costs no requests."""
    cache = os.path.join(ROOT, "output", f"history_{symbol}_{timeframe}.csv")
    os.makedirs(os.path.dirname(cache), exist_ok=True)
    if not fresh and os.path.exists(cache):
        frame = pd.read_csv(cache, index_col=0, parse_dates=True)
        frame.index = pd.to_datetime(frame.index, utc=True)
        if len(frame) >= min(bars, 1000):
            print(f"cache hit: {cache} ({len(frame)} bars)")
            return frame.tail(bars)
    frame = client.fetch_history(symbol, timeframe, total_bars=bars)
    if not frame.empty:
        frame.to_csv(cache)
        print(f"cached -> {cache}")
    return frame


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    fresh = "--fresh" in sys.argv
    ltf = args[0] if len(args) > 0 else "15m"
    htf = args[1] if len(args) > 1 else "1h"
    bars = int(args[2]) if len(args) > 2 else 20000

    client = get_delta_client()
    df_ltf = load_history(client, "BTCUSD", ltf, bars, fresh)
    # HTF needs ~4x the bars of the LTF window to cover the same span.
    df_htf = load_history(client, "BTCUSD", htf, bars * 4, fresh)
    # Drop the still-forming candle from each frame (confirm-only contract).
    df_ltf, df_htf = df_ltf.iloc[:-1], df_htf.iloc[:-1]
    days = (df_ltf.index[-1] - df_ltf.index[0]).days
    print(f"fetched ltf={len(df_ltf)} bars ({days} days) "
          f"{df_ltf.index[0]}..{df_ltf.index[-1]} | htf={len(df_htf)} bars")

    bt = BacktestConfig()
    report = walk_forward(df_ltf, df_htf, bt)
    text = report.to_text()
    print(text)

    log = os.path.join(ROOT, "output", "_walk_forward.log")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(text + "\n")
    print(f"\nsaved -> {log}")


if __name__ == "__main__":
    main()
