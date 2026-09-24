"""
Trading Bot v2 — Gradio Interface for HuggingFace Spaces
Minimal UI with background strategy execution.

The Space runs on ZeroGPU hardware (`zero-a10g`) — the only hosting tier
available to free personal accounts for Gradio Spaces. ZeroGPU requires that
the `spaces` module is imported and that at least one function bound to a
Gradio event handler is decorated with `@spaces.GPU`, otherwise startup fails
with "RuntimeError: No @spaces.GPU function detected during startup".
The trading logic itself is pure CPU (pandas/numpy).
"""

import os
import sys
import time
import threading
from pathlib import Path
from datetime import datetime, timezone

# ZeroGPU: import before anything that could touch CUDA/torch. Outside of
# ZeroGPU this package is a no-op, so the same file also runs on a normal CPU
# host (`pip install spaces` is only needed for local runs).
import spaces

import gradio as gr

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import (
    ALL_TICKERS,
    HTF,
    LTF,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)

# ─── Shared signal state (written by the bot loop, read by the UI) ──────────
_state_lock = threading.Lock()
_signal_history: list = []  # newest first; capped at _HISTORY_CAP
_HISTORY_CAP = 50
_STATUS_IDLE = "Idle — background loop runs every 15 min, or click Refresh."

SIGNAL_HEADERS = ["Symbol", "Signal", "Entry", "SL", "TP", "RRR", "HTF Trend"]


@spaces.GPU(duration=10)
def zerogpu_status() -> str:
    """
    Health check for the ZeroGPU slot.

    ZeroGPU's startup scan walks Gradio's registered event handlers and refuses
    to boot the Space unless at least one of them is decorated with
    `@spaces.GPU`. This handler is that function: it reserves a GPU for ~10 s
    (billed by effective runtime, which is milliseconds) and reports which
    device served the call.
    """
    try:
        import torch

        if torch.cuda.is_available():
            return f"✅ ZeroGPU OK — served by {torch.cuda.get_device_name(0)}"
        return "✅ ZeroGPU reachable — CUDA was not reported for this call"
    except Exception as exc:  # pragma: no cover - defensive
        return f"⚠️ ZeroGPU reachable but torch is unavailable: {exc}"


def _record_signals(new_signals: list) -> None:
    """Store freshly generated signals in the shared history (newest first)."""
    if not new_signals:
        return
    with _state_lock:
        for sig in reversed(new_signals):
            _signal_history.insert(0, sig)
        del _signal_history[_HISTORY_CAP:]


def _signal_to_row(sig: dict) -> list:
    def _num(value, ndigits=5):
        try:
            return round(float(value), ndigits)
        except (TypeError, ValueError):
            return None

    return [
        sig.get("symbol", ""),
        sig.get("signal", ""),
        _num(sig.get("entry")),
        _num(sig.get("sl")),
        _num(sig.get("tp")),
        _num(sig.get("rrr"), 2),
        sig.get("htf_trend", ""),
    ]


def _history_rows() -> list:
    """Shared signal history rendered as DataFrame rows."""
    with _state_lock:
        signals = list(_signal_history)
    return [_signal_to_row(s) for s in signals]


def _latest_chart_path():
    """Path of the most recent signal chart that still exists on disk."""
    with _state_lock:
        signals = list(_signal_history)
    for sig in signals:
        path = sig.get("chart_path")
        if path and Path(path).exists():
            return path
    return None

def refresh_signals():
    """Run one analysis pass now and refresh table + chart + status."""
    started = time.time()
    try:
        from main import run_analysis_once

        new_signals = run_analysis_once()
        _record_signals(new_signals)
    except Exception as exc:  # defensive: never crash the UI callback
        return _history_rows(), _latest_chart_path(), f"⚠️ Refresh failed: {exc}"

    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    elapsed = f"{time.time() - started:.1f}s"
    if new_signals:
        status = f"✅ {len(new_signals)} new signal(s) — updated {stamp} ({elapsed})"
    else:
        status = f"ℹ️ No new signals this run — updated {stamp} ({elapsed})"
    return _history_rows(), _latest_chart_path(), status


def initial_view():
    """Snapshot of whatever the background loop has produced so far."""
    rows = _history_rows()
    status = (
        f"{len(rows)} signal(s) loaded from the background loop."
        if rows
        else _STATUS_IDLE
    )
    return rows, _latest_chart_path(), status


def run_bot_loop():
    """
    Background thread that runs the trading strategy every 15 minutes.
    """
    from main import run_analysis_once

    while True:
        try:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Running analysis...")
            signals = run_analysis_once()
            _record_signals(signals)
            print(f"[Bot] Generated {len(signals)} signal(s)")
        except Exception as e:
            print(f"[Bot] Error: {e}")

        # Sleep for 15 minutes
        time.sleep(15 * 60)

# Gradio Interface
with gr.Blocks(
    title="Trading Bot v2",
) as demo:
    gr.Markdown(
        """
        # 🤖 Trading Bot v2

        **Status:** ✅ Active — Running in background

        ---
        """
    )

    gr.Markdown(
        f"""
        ## Configuration

        | Parameter | Value |
        |-----------|-------|
        | Tickers | {', '.join(ALL_TICKERS)} |
        | HTF | {HTF} |
        | LTF | {LTF} |
        | Telegram | {'✅ Configured' if TELEGRAM_BOT_TOKEN else '❌ Not configured'} |
        """
    )

    gr.Markdown(
        """
        ## How It Works

        1. **Data Fetching:** Candles are fetched every 15 minutes via yfinance
        2. **Analysis:** Swing points, S/R zones, and trend are computed
        3. **Signal Generation:** BUY/SELL signals based on price proximity to S/R
        4. **Risk Management:** ATR-based SL/TP with RRR validation
        5. **Alerts:** Charts and signals sent via Telegram

        ⚠️ **Manual Mode:** All trades require manual execution on your exchange.

        ---
        """
    )

    gr.Markdown(
        """
        ## Signals

        Generated signals are appended here (and sent to Telegram when configured).
        """
    )

    with gr.Row():
        refresh_button = gr.Button("🔄 Refresh Signals", variant="primary")

    status_box = gr.Textbox(label="Status", value=_STATUS_IDLE, interactive=False)

    signal_table = gr.DataFrame(
        headers=SIGNAL_HEADERS,
        value=[],
        label="Recent Trading Signals",
        interactive=False,
    )

    chart_output = gr.Image(
        label="Latest Signal Chart",
        type="filepath",
        height=520,
        interactive=False,
    )

    gr.Markdown(
        """
        ## Recent Activity

        *Check Telegram for full signal history and chart archive.*
        """
    )

    # ZeroGPU health check — the handler bound here is decorated with
    # @spaces.GPU, which ZeroGPU requires to boot the Space.
    with gr.Row():
        zerogpu_button = gr.Button("Check ZeroGPU slot", variant="secondary")
        zerogpu_output = gr.Textbox(label="GPU status", interactive=False)

    zerogpu_button.click(fn=zerogpu_status, inputs=None, outputs=zerogpu_output)

    refresh_button.click(
        fn=refresh_signals,
        inputs=None,
        outputs=[signal_table, chart_output, status_box],
    )
    demo.load(
        fn=initial_view,
        inputs=None,
        outputs=[signal_table, chart_output, status_box],
    )


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()
    demo.launch(theme=gr.themes.Soft())


