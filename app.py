"""Trading Bot v3 Gradio operations dashboard."""
import sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
import spaces
import gradio as gr
sys.path.insert(0, str(Path(__file__).parent))
from operations import (dashboard_snapshot, monitor_paper_positions, next_scan_at,
                        parse_time, record_heartbeat, signal_row, position_row, closed_row)
from storage import get_store

_state_lock=threading.Lock(); _analysis_lock=threading.Lock(); _signal_history=[]; _HISTORY_CAP=50
SIGNAL_HEADERS=["Symbol","Signal","Entry","SL","TP","RRR","HTF Trend","Status","Telegram","Created UTC"]
POSITION_HEADERS=["ID","Symbol","Side","Entry","Quantity","SL","TP","Status","Opened UTC"]
CLOSED_HEADERS=["ID","Symbol","Side","Entry","Exit","P&L","Exit reason","Closed UTC"]

@spaces.GPU(duration=10)
def zerogpu_status():
    try:
        import torch
        return f"ZeroGPU OK - {torch.cuda.get_device_name(0)}" if torch.cuda.is_available() else "ZeroGPU reachable; CUDA not reported"
    except Exception as exc:
        return f"ZeroGPU reachable; torch unavailable: {exc}"

def _record_signals(items):
    if not items: return
    with _state_lock:
        for sig in reversed(items): _signal_history.insert(0,sig)
        del _signal_history[_HISTORY_CAP:]

def _outputs(snapshot=None):
    s=snapshot or dashboard_snapshot()
    return [s["health_markdown"],s["metrics"],[signal_row(x) for x in s["signals"]],
            [position_row(x) for x in s["positions"]],[closed_row(x) for x in s["closed"]],
            s["chart"],s["status"]]

def initial_view(): return _outputs()
def refresh_signals():
    if not _analysis_lock.acquire(blocking=False):
        s=dashboard_snapshot(); return _outputs(s)+[ "Analysis already running; current data shown." ]
    try:
        from main import run_analysis_once
        started=time.time(); new=run_analysis_once(); _record_signals(new); closed=monitor_paper_positions()
        note=f"{len(new)} new signal(s); {len(closed)} paper exit(s); {time.time()-started:.1f}s"
    except Exception as exc:
        record_heartbeat("ERROR",last_error=str(exc)); note=f"Refresh failed: {exc}"
    finally:
        _analysis_lock.release()
    return _outputs()+[note]

def run_bot_loop():
    from main import run_analysis_once
    while True:
        try:
            if not _analysis_lock.acquire(blocking=False):
                record_heartbeat("RUNNING",last_error="Previous analysis still running")
            else:
                try:
                    record_heartbeat("RUNNING")
                    signals=run_analysis_once(); _record_signals(signals); closed=monitor_paper_positions()
                    record_heartbeat("RUNNING",last_signal_count=len(signals),last_closed_count=len(closed))
                finally: _analysis_lock.release()
        except Exception as exc:
            record_heartbeat("ERROR",last_error=str(exc))
        target=next_scan_at(); get_store().set_state("next_scan_at",target.isoformat())
        delay=max(1.0,(target-datetime.now(timezone.utc)).total_seconds()); time.sleep(delay)

with gr.Blocks(title="Trading Bot v3") as demo:
    gr.Markdown("# Trading Bot v3\nPersistent signal generation, paper execution, and operations monitoring. **No live exchange orders are submitted.**")
    health=gr.Markdown()
    with gr.Row():
        refresh_button=gr.Button("Refresh analysis",variant="primary")
        zerogpu_button=gr.Button("Check ZeroGPU")
    gpu=gr.Textbox(label="Infrastructure",interactive=False)
    metrics=gr.DataFrame(headers=["Metric","Value"],label="Operations summary",interactive=False,wrap=True)
    status=gr.Textbox(label="Last analysis",interactive=False)
    note=gr.Textbox(label="Action result",interactive=False)
    with gr.Tabs():
        with gr.Tab("Signals"):
            signals=gr.DataFrame(headers=SIGNAL_HEADERS,label="Stored signals",interactive=False,wrap=True)
            chart=gr.Image(label="Latest signal chart",type="filepath",height=500)
        with gr.Tab("Paper positions"):
            positions=gr.DataFrame(headers=POSITION_HEADERS,label="Position history",interactive=False,wrap=True)
        with gr.Tab("Closed trades"):
            closed=gr.DataFrame(headers=CLOSED_HEADERS,label="Closed paper trades",interactive=False,wrap=True)
    with gr.Accordion("Configuration and safety",open=True):
        gr.Markdown("Execution remains `PAPER`; OpenAlgo and exchange execution are disabled. The kill switch and daily-loss/open-position limits are enforced before simulated position creation. Telegram shows configured/not configured; delivery status is recorded per signal.")
    zerogpu_button.click(zerogpu_status,outputs=gpu)
    outputs=[health,metrics,signals,positions,closed,chart,status]
    refresh_button.click(refresh_signals,outputs=outputs+[note])
    demo.load(initial_view,outputs=outputs)

if __name__=="__main__":
    record_heartbeat("STARTING")
    threading.Thread(target=run_bot_loop,daemon=True,name="trading-bot-loop").start()
    demo.launch(theme=gr.themes.Soft())

