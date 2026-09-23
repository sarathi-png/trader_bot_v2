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


def run_bot_loop():
    """
    Background thread that runs the trading strategy every 15 minutes.
    """
    # Import main module components
    from main import run_analysis_once

    while True:
        try:
            print(f"[{datetime.now(timezone.utc).isoformat()}] Running analysis...")
            signals = run_analysis_once()
            print(f"[Bot] Generated {len(signals)} signal(s)")
        except Exception as e:
            print(f"[Bot] Error: {e}")

        # Sleep for 15 minutes
        time.sleep(15 * 60)


# Gradio Interface
with gr.Blocks(
    title="Trading Bot v2",
    theme=gr.themes.Soft(),
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

        1. **Data Fetching:** Candles are fetched every 15 minutes via CCXT
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
        ## Recent Activity

        *Check Telegram for signal history and charts.*
        """
    )

    # ZeroGPU health check — the handler bound here is decorated with
    # @spaces.GPU, which ZeroGPU requires to boot the Space.
    with gr.Row():
        zerogpu_button = gr.Button("Check ZeroGPU slot", variant="secondary")
        zerogpu_output = gr.Textbox(label="GPU status", interactive=False)

    zerogpu_button.click(fn=zerogpu_status, inputs=None, outputs=zerogpu_output)


if __name__ == "__main__":
    bot_thread = threading.Thread(target=run_bot_loop, daemon=True)
    bot_thread.start()
    demo.launch()