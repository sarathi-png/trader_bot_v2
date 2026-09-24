"""
Trading Bot v2 — Main Entry Point
Orchestrates data fetching, analysis, signal generation, and alerting.
Runs once per execution (manual mode) or loops every 15 min.
"""

import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    TICKERS,
    ALL_TICKERS,
    HTF,
    LTF,
    RISK_PCT,
    MIN_RRR,
    ATR_MULT,
    N_SWING,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    EXCHANGE_NAME,
    ACCOUNT_BALANCE,
    CHART_DIR,
    ZONE_TOLERANCE_PCT,
    DEDUPE_ENABLED,
    KILL_SWITCH,
    EXECUTION_MODE,
)

from data.streamer import fetch_recent_candles
from engine.indicators import atr_14
from engine.sr_zones import find_swing_high_low, cluster_zones, find_nearest_zones
from engine.trendlines import get_trend_direction
from engine.risk_engine import calc_sl_tp, calc_position_size, validate_rrr
from charting.plotter import generate_signal_chart
from alerts.telegram import send_telegram_signal, format_signal_caption
from execution.broker import paper_order_stub
from storage import get_store

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def analyze_symbol(
    symbol: str,
    htf: str = HTF,
    ltf: str = LTF,
    exchange_name: str = EXCHANGE_NAME,
) -> Optional[Dict[str, Any]]:
    """
    Analyze a single symbol and generate a trading signal.

    Pipeline:
    1. Fetch HTF candles for trend bias
    2. Fetch LTF candles for entry signal
    3. Compute ATR on LTF
    4. Find swing points and S/R zones on LTF
    5. Determine HTF trend direction
    6. Generate signal if price near S/R + trend alignment
    7. Calculate SL/TP using ATR
    8. Validate RRR meets minimum threshold

    Args:
        symbol: Trading pair symbol
        htf: Higher timeframe for trend
        ltf: Lower timeframe for entry
        exchange_name: CCXT exchange name

    Returns:
        Dict with signal details or None if no valid signal
    """
    if KILL_SWITCH:
        logger.warning("Kill switch active; analysis skipped")
        return None
    logger.info(f"Analyzing {symbol}...")

    # ─── Step 1: Fetch HTF data ──────────────────────────────────────────
    df_htf = fetch_recent_candles(symbol, htf, limit=200, exchange_name=exchange_name)
    if df_htf.empty:
        logger.warning(f"  No HTF data for {symbol}, skipping")
        return None

    # ─── Step 2: Fetch LTF data ──────────────────────────────────────────
    df_ltf = fetch_recent_candles(symbol, ltf, limit=200, exchange_name=exchange_name)
    if df_ltf.empty:
        logger.warning(f"  No LTF data for {symbol}, skipping")
        return None

    # ─── Step 3: Compute ATR on LTF ─────────────────────────────────────
    df_ltf = df_ltf.copy()
    df_ltf["atr"] = atr_14(df_ltf, period=14)

    if df_ltf["atr"].isna().all():
        logger.warning(f"  ATR all NaN for {symbol}, skipping")
        return None

    current_atr = df_ltf["atr"].iloc[-1]
    current_price = df_ltf["close"].iloc[-1]
    logger.info(f"  Current price: {current_price:.4f}, ATR: {current_atr:.4f}")

    # ─── Step 4: Find S/R zones on LTF ───────────────────────────────────
    df_ltf = find_nearest_zones(df_ltf, n=N_SWING, tolerance_pct=ZONE_TOLERANCE_PCT)

    nearest_support = df_ltf["nearest_support"].iloc[-1]
    nearest_resistance = df_ltf["nearest_resistance"].iloc[-1]

    logger.info(f"  Support: {nearest_support}, Resistance: {nearest_resistance}")

    # ─── Step 5: Determine HTF trend direction ───────────────────────────
    df_htf_swings = find_swing_high_low(df_htf, n=N_SWING)
    htf_trend = get_trend_direction(df_htf_swings, n_swings=N_SWING)
    df_htf_zones = find_nearest_zones(df_htf, n=N_SWING, tolerance_pct=ZONE_TOLERANCE_PCT)
    htf_support = df_htf_zones["nearest_support"].iloc[-1]
    htf_resistance = df_htf_zones["nearest_resistance"].iloc[-1]
    logger.info(f"  HTF Trend: {htf_trend}; zones: {htf_support}, {htf_resistance}")

    # ─── Step 6: Generate signal ─────────────────────────────────────────
    signal = None
    signal_type = None

    if nearest_support is not None and nearest_resistance is not None:
        # Define proximity threshold (within 0.5 * ATR of S/R)
        proximity = 0.5 * current_atr

        # BUY signal: Price near support + bullish HTF trend
        if (
            abs(current_price - nearest_support) < proximity
            and htf_trend in ("uptrend", "ranging")
        ):
            signal_type = "BUY"
            signal = {
                "symbol": symbol,
                "signal": "BUY",
                "entry": current_price,
                "support": nearest_support,
                "resistance": nearest_resistance,
                "htf_trend": htf_trend,
            }

        # SELL signal: Price near resistance + bearish HTF trend
        elif (
            abs(current_price - nearest_resistance) < proximity
            and htf_trend in ("downtrend", "ranging")
        ):
            signal_type = "SELL"
            signal = {
                "symbol": symbol,
                "signal": "SELL",
                "entry": current_price,
                "support": nearest_support,
                "resistance": nearest_resistance,
                "htf_trend": htf_trend,
            }

    if signal is None:
        logger.info(f"  No signal for {symbol} (price not near S/R or trend mismatch)")
        return None

    # ─── Step 7: Calculate SL/TP ─────────────────────────────────────────
    sl_tp = calc_sl_tp(
        df=df_ltf,
        entry_price=current_price,
        trend="long" if signal_type == "BUY" else "short",
        atr_mult=ATR_MULT,
        min_rrr=MIN_RRR,
        htf_support=htf_support,
        htf_resistance=htf_resistance,
    )

    if not sl_tp["valid"]:
        logger.info(f"  Signal invalid (RRR {sl_tp['rrr']:.2f} < {MIN_RRR})")
        return None

    # ─── Step 8: Combine results ─────────────────────────────────────────
    result = {
        **signal,
        "sl": sl_tp["sl"],
        "tp": sl_tp["tp"],
        "atr": sl_tp["atr"],
        "rrr": sl_tp["rrr"],
        "risk": sl_tp["risk"],
        "reward": sl_tp["reward"],
        "timeframe": ltf,
        "source_candle": df_ltf.index[-1].isoformat(),
    }

    logger.info(
        f"  ✅ {signal_type} signal: Entry={current_price:.4f}, "
        f"SL={sl_tp['sl']:.4f}, TP={sl_tp['tp']:.4f}, RRR={sl_tp['rrr']:.2f}"
    )

    return result


def process_signal(signal_data: Dict[str, Any]) -> Optional[str]:
    """
    Process a complete signal: generate chart, send Telegram alert.

    Args:
        signal_data: Complete signal dictionary from analyze_symbol

    Returns:
        Path to generated chart, or None on failure
    """
    symbol = signal_data["symbol"]
    signal_type = signal_data["signal"]

    # Fetch LTF data for chart
    df_ltf = fetch_recent_candles(symbol, LTF, limit=200, exchange_name=EXCHANGE_NAME)
    if df_ltf.empty:
        logger.error(f"Cannot generate chart for {symbol}: no data")
        return None

    # Add ATR for chart reference
    df_ltf["atr"] = atr_14(df_ltf, period=14)

    # Generate chart
    chart_path = str(CHART_DIR / f"{symbol.replace('/', '_')}_{signal_type}_{int(time.time())}.png")

    try:
        chart_file = generate_signal_chart(
            df=df_ltf,
            support=signal_data.get("support"),
            resistance=signal_data.get("resistance"),
            sl=signal_data.get("sl"),
            tp=signal_data.get("tp"),
            entry=signal_data.get("entry"),
            signal=signal_type,
            symbol=symbol,
            output_path=chart_path,
        )
        logger.info(f"  Chart saved: {chart_file}")
    except Exception as e:
        logger.error(f"  Chart generation failed: {e}")
        chart_file = None

    # Format Telegram caption
    caption = format_signal_caption(
        symbol=symbol,
        signal=signal_type,
        entry=signal_data["entry"],
        sl=signal_data["sl"],
        tp=signal_data["tp"],
        support=signal_data.get("support"),
        resistance=signal_data.get("resistance"),
        rrr=signal_data.get("rrr"),
        timeframe=LTF,
    )

    # Send Telegram alert; delivery status is persisted independently of chart creation.
    telegram_status = "NOT_CONFIGURED"
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and chart_file:
        telegram_status = "SENT" if send_telegram_signal(
            bot_token=TELEGRAM_BOT_TOKEN,
            chat_id=TELEGRAM_CHAT_ID,
            image_path=chart_file,
            caption_str=caption,
        ) else "FAILED"
    signal_data["telegram_status"] = telegram_status

    # Paper order is deliberately local and never submits a live exchange order.
    if EXECUTION_MODE == "PAPER":
        order = paper_order_stub(
            symbol=symbol, side="buy" if signal_type == "BUY" else "sell",
            qty=0.001, sl=signal_data.get("sl"), tp=signal_data.get("tp"),
        )
        get_store().insert_order(order, signal_data.get("signal_key"))
        signal_data["order_id"] = order.get("order_id")
    return chart_file


def run_analysis_once() -> list:
    """Run one persisted analysis pass and return only new, non-duplicate signals."""
    store = get_store(); run_id = store.start_run(len(ALL_TICKERS))
    signals=[]; ok=0; errors=0; details=[]
    logger.info("Running v3 analysis; tickers=%s HTF=%s LTF=%s", ALL_TICKERS, HTF, LTF)
    for ticker in ALL_TICKERS:
        try:
            signal = analyze_symbol(ticker); ok += 1
            if not signal:
                details.append({"symbol": ticker, "result": "NO_SIGNAL"}); continue
            candle = signal.get("source_candle", datetime.now(timezone.utc).isoformat())
            signal["signal_key"] = store.make_signal_key(ticker, LTF, signal["signal"], candle)
            if DEDUPE_ENABLED and not store.insert_signal(signal):
                logger.info("Duplicate signal suppressed: %s", signal["signal_key"]); continue
            signal["chart_path"] = process_signal(signal)
            if signal["chart_path"]: store.update_signal(signal["signal_key"], chart_path=signal["chart_path"], status="ALERTED")
            signals.append(signal); details.append({"symbol": ticker, "result": "SIGNAL", "key": signal["signal_key"]})
        except Exception as exc:
            errors += 1; logger.exception("Error analyzing %s", ticker); details.append({"symbol": ticker, "result": "ERROR", "error": str(exc)})
    store.finish_run(run_id, ok, len(signals), errors, {"details": details})
    logger.info("Analysis complete: analyzed=%s signals=%s errors=%s", ok, len(signals), errors)
    return signals


def main():
    """
    Main entry point for the trading bot.

    Manual mode (default): Runs once and exits.
    Set TRADING_BOT_LOOP=true env var for continuous 15-min loop.
    """
    import os

    loop_mode = os.getenv("TRADING_BOT_LOOP", "false").lower() == "true"

    if loop_mode:
        logger.info("Starting in LOOP mode (every 15 minutes)")
        while True:
            try:
                run_analysis_once()
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")

            from config.settings import SCAN_INTERVAL_MINUTES, SCHEDULE_OFFSET_SECONDS
            now=datetime.now(timezone.utc); interval=SCAN_INTERVAL_MINUTES*60; next_close=((now.timestamp()+SCHEDULE_OFFSET_SECONDS)//interval+1)*interval
            delay=max(1,next_close-now.timestamp()); logger.info("Sleeping until next aligned scan in %.0fs",delay); time.sleep(delay)
    else:
        logger.info("Running in MANUAL mode (single execution)")
        signals = run_analysis_once()
        if signals:
            logger.info(f"Generated {len(signals)} signal(s)")
        else:
            logger.info("No signals generated")


if __name__ == "__main__":
    main()
