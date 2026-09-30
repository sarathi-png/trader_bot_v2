"""
Execution mode control and safety gates (Stage 4).

Modes:
  MANUAL  analysis + alerts only; no position is ever opened
  PAPER   simulated positions via PaperBroker (the default)
  LIVE    real orders — REFUSED unless every gate below passes

LIVE is gated on evidence, not on a config flag. It stays locked until the
recorded paper track record clears a minimum sample, and arming it
requires typing an exact confirmation phrase. There is no testnet on
Delta Exchange India, so LIVE always means real money.

The kill switch is a runtime, persistent flag. It overrides the
configured mode so that engaging it forces PAPER immediately, whatever
config says, without a restart.
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

KILL_SWITCH_KEY = "kill_switch"
MODE_KEY = "execution_mode"


class ExecutionMode(str, Enum):
    MANUAL = "MANUAL"
    PAPER = "PAPER"
    LIVE = "LIVE"

    @classmethod
    def parse(cls, value: Any) -> "ExecutionMode":
        """Coerce arbitrary input to a mode, defaulting to the safe PAPER."""
        try:
            return cls(str(value).strip().upper())
        except (ValueError, AttributeError):
            logger.warning("Unknown EXECUTION_MODE %r; falling back to PAPER", value)
            return cls.PAPER


def confirmation_phrase() -> str:
    """Exact phrase a human must type to arm LIVE mode."""
    return os.getenv("LIVE_CONFIRM_PHRASE", "ENABLE LIVE TRADING")


# ─── runtime state (persisted in app_state, survives restarts) ───────────────

def _store():
    from storage import get_store
    return get_store()


def kill_switch_active() -> bool:
    if os.getenv("KILL_SWITCH", "false").lower() == "true":
        return True
    return _store().get_state(KILL_SWITCH_KEY, "false") == "true"


def engage_kill_switch(reason: str = "manual") -> Dict[str, Any]:
    """Single action to stop trading. Forces PAPER immediately and persists."""
    store = _store()
    store.set_state(KILL_SWITCH_KEY, "true")
    store.set_state(MODE_KEY, ExecutionMode.PAPER.value)
    store.set_state("kill_switch_reason", reason)
    logger.warning("KILL SWITCH ENGAGED (%s) — execution forced to PAPER", reason)
    return {"kill_switch": True, "mode": ExecutionMode.PAPER.value, "reason": reason}


def release_kill_switch(phrase: str) -> Tuple[bool, str]:
    """Clear the kill switch. Requires the confirmation phrase for safety."""
    if phrase.strip() != confirmation_phrase():
        return False, "Incorrect confirmation phrase; kill switch stays engaged"
    _store().set_state(KILL_SWITCH_KEY, "false")
    logger.warning("Kill switch released")
    return True, "Kill switch released"


def configured_mode() -> ExecutionMode:
    """Mode from config/.env, unless a runtime override is recorded."""
    override = _store().get_state(MODE_KEY)
    if override:
        return ExecutionMode.parse(override)
    from config.settings import EXECUTION_MODE
    return ExecutionMode.parse(EXECUTION_MODE)


def paper_track_record() -> Dict[str, Any]:
    """Win rate and expectancy over recorded closed paper trades.

    This is the evidence LIVE mode is gated on. It is computed from
    storage rather than from a config value, so a track record cannot be
    asserted into existence.
    """
    closed = [p for p in _store().recent_closed_positions(1000) if p.get("pnl") is not None]
    if not closed:
        return {"trades": 0, "win_rate": 0.0, "expectancy": 0.0, "total_pnl": 0.0}
    pnls = [float(p["pnl"]) for p in closed]
    wins = [p for p in pnls if p > 0]
    return {
        "trades": len(pnls),
        "win_rate": round(100.0 * len(wins) / len(pnls), 1),
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "total_pnl": round(sum(pnls), 2),
    }


def live_gate_report() -> Tuple[bool, str]:
    """Check every condition that must hold before real-money orders.

    Returns (allowed, human-readable reason). Deliberately conservative:
    a missing record, a thin sample, or non-positive expectancy all keep
    LIVE locked. Lives here rather than in operations because the mode
    logic must not depend on the operations layer.
    """
    from config.settings import LIVE_MIN_PAPER_TRADES, LIVE_MIN_WIN_RATE_PCT
    track = paper_track_record()
    if track["trades"] < LIVE_MIN_PAPER_TRADES:
        return False, (f"LIVE blocked: {track['trades']}/{LIVE_MIN_PAPER_TRADES} "
                       f"paper trades recorded")
    if track["win_rate"] < LIVE_MIN_WIN_RATE_PCT:
        return False, (f"LIVE blocked: win rate {track['win_rate']}% is below "
                       f"the required {LIVE_MIN_WIN_RATE_PCT}%")
    if track["expectancy"] <= 0:
        return False, (f"LIVE blocked: expectancy {track['expectancy']} per trade "
                       f"is not above breakeven")
    if kill_switch_active():
        return False, "LIVE blocked: kill switch is engaged"
    return True, (f"LIVE gate satisfied: {track['trades']} paper trades, "
                  f"{track['win_rate']}% win rate, expectancy {track['expectancy']}")


def request_mode_change(target: Any, phrase: str = "") -> Tuple[bool, str]:
    """Attempt to switch execution mode at runtime.

    Moving to LIVE requires BOTH an exact confirmation phrase and a
    passing evidence gate. Moving to MANUAL/PAPER is always allowed.
    """
    mode = ExecutionMode.parse(target)
    store = _store()
    if mode is ExecutionMode.LIVE:
        if phrase.strip() != confirmation_phrase():
            store.set_state("live_lockout_reason", "incorrect confirmation phrase")
            return False, ("Refusing LIVE: confirmation phrase does not match. "
                           f'Type exactly: "{confirmation_phrase()}"')
        allowed, reason = live_gate_report()
        if not allowed:
            store.set_state("live_lockout_reason", reason)
            return False, reason
        store.set_state("live_lockout_reason", "")
    if kill_switch_active() and mode is not ExecutionMode.PAPER:
        return False, "Kill switch is engaged; release it before changing mode"
    store.set_state(MODE_KEY, mode.value)
    logger.warning("Execution mode set to %s", mode.value)
    return True, f"Execution mode set to {mode.value}"


def mode_snapshot() -> Dict[str, Any]:
    """Current mode, kill-switch state, and LIVE gate status for dashboards."""
    allowed, reason = live_gate_report()
    configured = configured_mode()
    return {
        "configured_mode": configured.value,
        "effective_mode": effective_mode().value,
        "kill_switch": kill_switch_active(),
        "live_allowed": allowed,
        "live_gate_reason": reason,
        "track_record": paper_track_record(),
    }


def effective_mode() -> ExecutionMode:
    """The mode that actually governs order placement right now."""
    if kill_switch_active():
        return ExecutionMode.PAPER
    mode = configured_mode()
    if mode is ExecutionMode.LIVE:
        ok, _ = live_gate_report()
        if not ok:
            return ExecutionMode.PAPER
    return mode
