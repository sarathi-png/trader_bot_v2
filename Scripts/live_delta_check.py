"""Live end-to-end check of the Stage 1 Delta data path.

Run manually (needs internet):  python scripts/live_delta_check.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.delta_client import get_delta_client, resolve_delta_symbol
from data.quality import candle_staleness_reason, spread_reason
from data.streamer import fetch_recent_candles


def main():
    symbol = "BTC/USDT"
    dsym = resolve_delta_symbol(symbol)
    client = get_delta_client()
    print(f"delta symbol: {dsym} | listed: {client.is_listed(dsym)}")
    for tf in ("15m", "1h"):
        df = fetch_recent_candles(symbol, tf, limit=200, confirm_only=True)
        last = df.index[-1] if not df.empty else None
        print(f"{tf}: rows={len(df)} source={df.attrs.get('data_source')} "
              f"last_closed={last} close={df['close'].iloc[-1] if not df.empty else None} "
              f"staleness={candle_staleness_reason(df, tf, 2)}")
    quote = client.fetch_quote(dsym)
    print(f"quote: bid={quote['best_bid']} ask={quote['best_ask']} "
          f"mark={quote['mark_price']} spread={spread_reason(quote['best_bid'], quote['best_ask'], 0.5)}")
    t0 = time.time()
    for _ in range(3):
        client.fetch_candles(dsym, "15m", 5)
    print(f"throttled 3x candle fetches took {time.time() - t0:.2f}s "
          f"(expect >= ~0.6s at 5 rps cap)")


if __name__ == "__main__":
    main()
