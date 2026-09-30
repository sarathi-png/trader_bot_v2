"""Shared operations helpers for monitoring, risk checks, and UI formatting."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Tuple

from config.settings import (
    ACCOUNT_BALANCE, DB_PATH, EXECUTION_MODE, HTF, KILL_SWITCH, LTF,
    MAX_DAILY_LOSS_PCT, MAX_OPEN_POSITIONS, OPENALGO_ENABLED,
    PAPER_FEE_PCT, PAPER_SLIPPAGE_PCT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
)
from data.streamer import fetch_recent_candles
from execution.modes import (
    KILL_SWITCH_KEY, MODE_KEY, ExecutionMode, confirmation_phrase,
    configured_mode, effective_mode, engage_kill_switch, kill_switch_active,
    live_gate_report, mode_snapshot, paper_track_record, release_kill_switch,
    request_mode_change,
)
from execution.paper_engine import PaperBroker
from storage import get_store

logger = logging.getLogger(__name__)

_store = get_store


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_time(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def record_heartbeat(state: str, **details: Any) -> None:
    payload = {"state": state, "at": utc_now_iso(), **details}
    store = get_store()
    for key, value in payload.items():
        store.set_state(key, json.dumps(value) if isinstance(value, (dict, list)) else value)


def next_scan_at(now: datetime | None = None) -> datetime:
    from config.settings import SCAN_INTERVAL_MINUTES, SCHEDULE_OFFSET_SECONDS
    now = now or datetime.now(timezone.utc)
    interval = max(1, SCAN_INTERVAL_MINUTES) * 60
    timestamp = now.timestamp() - max(0, SCHEDULE_OFFSET_SECONDS)
    boundary = (int(timestamp // interval) + 1) * interval
    return datetime.fromtimestamp(boundary + max(0, SCHEDULE_OFFSET_SECONDS), tz=timezone.utc)


def current_bars(symbols: Iterable[str]) -> Dict[str, Dict[str, float]]:
    """Latest high/low/close per symbol, so intrabar stops are not missed."""
    bars: Dict[str, Dict[str, float]] = {}
    for symbol in dict.fromkeys(symbols):
        try:
            frame = fetch_recent_candles(symbol, LTF, limit=2)
            if not frame.empty:
                last = frame.iloc[-1]
                bars[symbol] = {"high": float(last["high"]),
                                "low": float(last["low"]),
                                "close": float(last["close"])}
        except Exception as exc:
            record_heartbeat("DEGRADED", last_error=f"Price monitor {symbol}: {exc}")
    return bars


def monitor_paper_positions() -> list[dict]:
    """Reconcile open paper positions against the latest closed candle.

    Called on every scan cycle. Without this half of the cycle positions
    never close, the open-position limit is reached, and every later entry
    is risk-blocked, so no track record can accumulate.
    """
    positions = get_store().open_positions()
    if not positions:
        return []
    bars = current_bars(p["symbol"] for p in positions)
    return PaperBroker(PAPER_FEE_PCT, PAPER_SLIPPAGE_PCT, MAX_OPEN_POSITIONS).check_exit(bars)


def can_open_position() -> Tuple[bool, str]:
    """Pre-order gate. Returns (allowed, reason).

    Enforced in order: kill switch, execution mode, portfolio limits,
    daily loss limit. LIVE additionally requires the evidence gate.
    """
    from config.settings import ACCOUNT_BALANCE, MAX_DAILY_LOSS_PCT, MAX_OPEN_POSITIONS

    if KILL_SWITCH or kill_switch_active():
        return False, "Kill switch engaged — no new positions"

    mode = effective_mode()
    if mode is ExecutionMode.MANUAL:
        return False, "MANUAL mode — signals only, no positions"

    store = _store()
    if store.open_positions_count() >= MAX_OPEN_POSITIONS:
        return False, f"Open position limit reached ({MAX_OPEN_POSITIONS})"

    daily_pnl = store.daily_realized_pnl()
    loss_limit = abs(ACCOUNT_BALANCE) * MAX_DAILY_LOSS_PCT / 100.0
    if loss_limit and daily_pnl <= -loss_limit:
        return False, (f"Daily loss limit hit ({daily_pnl:.2f} <= "
                       f"-{loss_limit:.2f}) — trading halted for today")

    if mode is ExecutionMode.LIVE:
        allowed, reason = live_gate_report()
        if not allowed:
            return False, reason

    return True, f"OK ({mode.value})"


def risk_snapshot() -> dict:
    store = get_store()
    daily_pnl = store.daily_realized_pnl()
    open_count = store.open_positions_count()
    loss_limit = abs(ACCOUNT_BALANCE) * MAX_DAILY_LOSS_PCT / 100
    return {
        "daily_pnl": daily_pnl,
        "daily_loss_limit": loss_limit,
        "loss_limit_used_pct": max(0.0, -daily_pnl / loss_limit * 100) if loss_limit else 0.0,
        "open_positions": open_count,
        "max_open_positions": MAX_OPEN_POSITIONS,
        "blocked": (KILL_SWITCH or kill_switch_active() or open_count >= MAX_OPEN_POSITIONS
                    or (loss_limit and daily_pnl <= -loss_limit)),
        "kill_switch": KILL_SWITCH or kill_switch_active(),
        "execution_mode": effective_mode().value,
        "configured_mode": configured_mode().value,
        "live_allowed": live_gate_report()[0],
        "live_gate_reason": live_gate_report()[1],
        "track_record": paper_track_record(),
    }




def dashboard_snapshot() -> dict:
    from config.settings import ALL_TICKERS
    store = get_store()
    health = store.health()
    signals = store.recent_signals(50)
    positions = store.recent_positions(50)
    closed = store.recent_closed_positions(50)
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    today_signals = [s for s in signals if str(s.get("created_at", "")).startswith(today)]
    runs_24h = store.runs_since(since)
    last = health.get("last_run") or {}
    next_scan = parse_time(store.get_state("next_scan_at")) or next_scan_at()
    last_finished = parse_time(last.get("finished_at"))
    stale = bool(last_finished and datetime.now(timezone.utc) - last_finished > timedelta(minutes=30))
    worker_state = store.get_state("worker_state", "STARTING")
    # During ZeroGPU replica replacement the persistent DB can briefly contain
    # STARTING from the prior container. A recent completed run is stronger
    # evidence that this dashboard is serving an active bot.
    if worker_state == "STARTING" and last_finished and datetime.now(timezone.utc) - last_finished <= timedelta(minutes=30):
        worker_state = "RUNNING"
    overall = "DEGRADED" if stale or worker_state == "ERROR" else worker_state
    return {
        "health_markdown": _health_markdown(overall, last, next_scan, stale),
        "metrics": _metrics(health, len(today_signals), len(runs_24h), risk_snapshot()),
        "signals": signals,
        "positions": positions,
        "closed": closed,
        "chart": _latest_chart(signals),
        "status": _status_text(last, len(today_signals), stale, worker_state),
        "telegram": "Configured" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "Not configured",
        "openalgo": "Enabled" if OPENALGO_ENABLED else "Disabled",
        "mode": EXECUTION_MODE,
        "tickers": list(ALL_TICKERS),
        "htf": HTF,
        "ltf": LTF,
    }


def _number(value: Any, digits: int = 2):
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def format_display_time(value: str | datetime | None) -> str:
    """Format a timestamp as YYYY-MM-DD:h.m AM/PM in UTC."""
    if isinstance(value, str):
        value = parse_time(value)
    if not isinstance(value, datetime):
        return "Never"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    hour = value.hour % 12 or 12
    return f"{value:%Y-%m-%d}:{hour}.{value:%M} {'AM' if value.hour < 12 else 'PM'} UTC"


def _health_markdown(state: str, last: dict, next_scan: datetime, stale: bool) -> str:
    icon = {"RUNNING": "🟢", "STARTING": "🟡", "DEGRADED": "🟠", "STOPPED": "🔴", "ERROR": "🔴"}.get(state, "⚪")
    last_text = last.get("finished_at") or last.get("started_at")
    last_display = format_display_time(last_text)
    next_display = format_display_time(next_scan)
    warning = " — last run is stale" if stale else ""
    return f"## Bot health: {icon} {state}{warning}\nLast run: `{last_display}`  \nScheduled run: `{next_display}`"


def _track_record_text(track: dict | None) -> str:
    """Progress toward the LIVE gate, in the same terms the gate uses."""
    if not track:
        return "no closed paper trades yet"
    return (f"{track.get('trades', 0)} trades, {track.get('win_rate', 0)}% win, "
            f"expectancy {track.get('expectancy', 0)}")


def _metrics(health: dict, today_signals: int, runs_24h: int, risk: dict) -> list[list]:
    return [
        ["Signals today", today_signals],
        ["Analysis runs (24h)", runs_24h],
        ["Total stored signals", health.get("signal_count", 0)],
        ["Open paper positions", f"{risk.get('open_positions', 0)} / {risk.get('max_open_positions', 0)}"],
        ["Paper track record", _track_record_text(risk.get("track_record"))],
        ["Daily realized P&L", _number(risk.get("daily_pnl", 0))],
        ["Daily loss used", f"{risk.get('loss_limit_used_pct', 0):.1f}%"],
        ["Execution mode", f"{risk.get('execution_mode')} (configured: {risk.get('configured_mode')})"],
        ["LIVE gate", "OPEN — criteria met" if risk.get("live_allowed") else risk.get("live_gate_reason")],
        ["Kill switch", "ON" if risk.get("kill_switch") else "OFF"],
        ["Telegram", "Configured" if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else "Not configured"],
        ["OpenAlgo", "Enabled" if OPENALGO_ENABLED else "Disabled"],
        ["Storage", str(DB_PATH)],
    ]


def signal_row(signal: dict) -> list:
    row = [signal.get(k) for k in ("symbol", "direction", "entry", "sl", "tp", "rrr", "htf_trend", "status", "telegram_status", "created_at")]
    score = signal.get("confluence_score")
    if score is None:  # stored signals keep the full payload in details_json
        try:
            score = json.loads(signal.get("details_json") or "{}").get("confluence_score")
        except (TypeError, ValueError):
            score = None
    row.insert(6, score)  # shown right after RRR
    return row


def position_row(position: dict) -> list:
    return [position.get(k) for k in ("id", "symbol", "side", "entry_price", "quantity", "sl", "tp", "status", "created_at")]


def closed_row(position: dict) -> list:
    return [position.get(k) for k in ("id", "symbol", "side", "entry_price", "exit_price", "pnl", "exit_reason", "closed_at")]


def _latest_chart(signals: list[dict]):
    from pathlib import Path
    for signal in signals:
        path = signal.get("chart_path")
        if path and Path(path).is_file():
            return path
    return None


def _status_text(last: dict, today_signals: int, stale: bool, worker_state: str) -> str:
    if stale:
        return f"DEGRADED — no recent completed run | signals today: {today_signals}"
    stamp = format_display_time(last.get("finished_at") or last.get("started_at"))
    return f"Last run: {stamp} | signals: {last.get('signals_found', 0)} | errors: {last.get('errors', 0)} | worker: {worker_state}"
