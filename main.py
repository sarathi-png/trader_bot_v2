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
    PAPER_FEE_PCT,
    PAPER_SLIPPAGE_PCT,
    MAX_OPEN_POSITIONS,
    MAX_POSITION_PCT,
    MAX_SPREAD_PCT,
    DATA_STALE_MAX_BARS,
)

from data.streamer import fetch_recent_candles
from data.delta_client import get_delta_client, resolve_delta_symbol
from data.quality import candle_staleness_reason, spread_reason
from operations import record_heartbeat
from engine.indicators import atr_14
from engine.sr_zones import find_swing_high_low, cluster_zones, find_nearest_zones
from engine.trendlines import get_trend_direction
from engine.risk_engine import calc_sl_tp, calc_position_size, validate_rrr
from engine.confluence import analyze_confluence, gate_signal
from charting.plotter import generate_signal_chart
from alerts.telegram import send_telegram_signal, format_signal_caption
from execution.broker import paper_order_stub
from execution.paper_engine import PaperBroker
from execution.modes import ExecutionMode, effective_mode
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

    # ─── Step 1: Fetch HTF data (closed candles only) ────────────────────
    df_htf = fetch_recent_candles(symbol, htf, limit=200, exchange_name=exchange_name, confirm_only=True)
    if df_htf.empty:
        logger.warning(f"  No HTF data for {symbol}, skipping")
        return None

    # ─── Step 2: Fetch LTF data (closed candles only) ────────────────────
    df_ltf = fetch_recent_candles(symbol, ltf, limit=200, exchange_name=exchange_name, confirm_only=True)
    if df_ltf.empty:
        logger.warning(f"  No LTF data for {symbol}, skipping")
        return None

    # ─── Step 2b: Data-quality gates (source health, staleness, spread) ──
    data_source = df_ltf.attrs.get("data_source", "yahoo")
    dsym = resolve_delta_symbol(symbol)
    if dsym and data_source != "delta":
        record_heartbeat(
            "DEGRADED",
            last_error=f"{symbol}: Delta unavailable, using {data_source} data",
        )
    stale = candle_staleness_reason(df_ltf, ltf, DATA_STALE_MAX_BARS) or \
        candle_staleness_reason(df_htf, htf, DATA_STALE_MAX_BARS)
    if stale:
        logger.warning(f"  {stale} for {symbol}, skipping signal")
        record_heartbeat("DEGRADED", last_error=f"{symbol}: {stale}")
        return None
    if data_source == "delta" and dsym:
        try:
            quote = get_delta_client().fetch_quote(dsym)
            wide = spread_reason(quote.get("best_bid"), quote.get("best_ask"), MAX_SPREAD_PCT)
            if wide:
                logger.warning(f"  {wide} for {symbol}, skipping signal")
                record_heartbeat("DEGRADED", last_error=f"{symbol}: {wide}")
                return None
        except Exception as exc:
            logger.warning("  Spread check failed for %s: %s", symbol, exc)

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

    # ─── Step 6b: Multi-TF confluence scoring + gate ──────────────────────
    confluence = analyze_confluence(df_ltf, df_htf)
    side = "long" if signal_type == "BUY" else "short"
    passed, gate_note = gate_signal(confluence, side)
    logger.info(
        f"  Confluence {confluence.direction} score={confluence.score}: "
        + " | ".join(confluence.reasons)
    )
    if not passed:
        logger.info(f"  Signal dropped by confluence gate: {gate_note}")
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
        **confluence.to_signal_fields(),
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

    # Paper execution is local, durable, and never submits exchange orders.
    mode = effective_mode()
    if mode is ExecutionMode.LIVE:
        # Deliberately not implemented. LIVE stays locked until the evidence
        # gate passes AND Stage 5 (idempotent placement + reconciliation) is
        # built. Until then we degrade to PAPER rather than pretend to trade.
        logger.error("LIVE mode requested but live execution is not implemented; using PAPER")
        record_heartbeat("DEGRADED", last_error="LIVE mode requested; falling back to PAPER")
        mode = ExecutionMode.PAPER
    if mode is ExecutionMode.PAPER:
        from operations import can_open_position
        from execution.paper_engine import RiskError
        allowed, reason = can_open_position()
        if not allowed:
            logger.warning("Paper position blocked by risk gate: %s", reason)
            get_store().update_signal(signal_data.get("signal_key"), status="RISK_BLOCKED")
            signal_data["final_status"] = "RISK_BLOCKED"
        else:
            risk_per_unit = abs(float(signal_data["entry"]) - float(signal_data["sl"]))
            sizing = calc_position_size(ACCOUNT_BALANCE, RISK_PCT, risk_per_unit, MAX_POSITION_PCT)
            sizing["quantity"] = min(sizing["quantity"], (ACCOUNT_BALANCE * MAX_POSITION_PCT / 100.0) / float(signal_data["entry"]))
            sizing["quantity"] = round(sizing["quantity"], 8)
            if sizing["quantity"] <= 0 or not sizing["valid"]:
                logger.warning("Paper position blocked by position sizing")
                get_store().update_signal(signal_data.get("signal_key"), status="RISK_BLOCKED")
                signal_data["final_status"] = "RISK_BLOCKED"
            else:
                try:
                    broker = PaperBroker(PAPER_FEE_PCT, PAPER_SLIPPAGE_PCT, MAX_OPEN_POSITIONS)
                    position = broker.open_position(signal_data, quantity=sizing["quantity"])
                    get_store().update_signal(signal_data.get("signal_key"), order_id=f"PAPER-POS-{position['id']}", status="PAPER_OPEN")
                    signal_data["position_id"] = position["id"]
                    signal_data["final_status"] = "PAPER_OPEN"
                except RiskError as exc:
                    logger.warning("Paper position rejected: %s", exc)
                    get_store().update_signal(signal_data.get("signal_key"), status="RISK_BLOCKED")
                    signal_data["final_status"] = "RISK_BLOCKED"
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
            store.update_signal(signal["signal_key"], chart_path=signal.get("chart_path"), telegram_status=signal.get("telegram_status"))
            final_status = signal.get("final_status") or ("ALERTED" if signal.get("chart_path") else "CHART_FAILED")
            store.update_signal(signal["signal_key"], status=final_status)
            signals.append(signal); details.append({"symbol": ticker, "result": "SIGNAL", "key": signal["signal_key"]})
        except Exception as exc:
            errors += 1; logger.exception("Error analyzing %s", ticker); details.append({"symbol": ticker, "result": "ERROR", "error": str(exc)})
    store.finish_run(run_id, ok, len(signals), errors, {"details": details})
    logger.info("Analysis complete: analyzed=%s signals=%s errors=%s", ok, len(signals), errors)
    return signals


def run_scan_cycle() -> tuple:
    """One scheduled cycle: generate signals, then reconcile open paper positions.

    Both halves matter. Analysis alone opens positions that are never
    closed, which fills the open-position limit and risk-blocks every later
    entry, so a paper track record can never accumulate.
    """
    from operations import monitor_paper_positions
    signals = run_analysis_once()
    closed = monitor_paper_positions()
    return signals, closed


def main():
    """
    Main entry point for the trading bot.

    Manual mode (default): Runs once and exits.
    Set TRADING_BOT_LOOP=true env var for continuous 15-min loop.
    """
    import os

    loop_mode = os.getenv("TRADING_BOT_LOOP", "false").lower() == "true"

    if loop_mode:
        from config.settings import SCAN_INTERVAL_MINUTES
        from operations import next_scan_at
        logger.info("Starting in LOOP mode (every %s minutes)", SCAN_INTERVAL_MINUTES)
        while True:
            try:
                signals, closed = run_scan_cycle()
                logger.info("Scan complete: %s new signal(s), %s paper exit(s)",
                            len(signals), len(closed))
            except KeyboardInterrupt:
                logger.info("Bot stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")

            target = next_scan_at()
            delay = max(1.0, (target - datetime.now(timezone.utc)).total_seconds())
            logger.info("Sleeping until next aligned scan in %.0fs", delay)
            time.sleep(delay)
    else:
        logger.info("Running in MANUAL mode (single execution)")
        signals = run_analysis_once()
        if signals:
            logger.info(f"Generated {len(signals)} signal(s)")
        else:
            logger.info("No signals generated")


if __name__ == "__main__":
    main()
