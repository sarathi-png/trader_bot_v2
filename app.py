"""Trading Bot v3 Gradio operations dashboard."""
import sys, threading, time
from datetime import datetime, timezone
from pathlib import Path
import spaces
import gradio as gr
sys.path.insert(0, str(Path(__file__).parent))
from operations import (dashboard_snapshot, monitor_paper_positions, next_scan_at,
                        parse_time, record_heartbeat, signal_row, position_row, closed_row)
from execution.modes import engage_kill_switch
from operations import mode_snapshot, release_kill_switch, request_mode_change
from storage import get_store
from config.settings import CHART_DIR

# Gradio refuses to hand out files it did not create, so charts written to the
# mounted persistent volume (/data/charts on a Space) must be explicitly
# allowed. Without this every page load fails as soon as one chart exists.
ALLOWED_PATHS = [str(CHART_DIR)]

_state_lock=threading.Lock(); _analysis_lock=threading.Lock(); _worker_lock=threading.Lock(); _worker_started=False
_signal_history=[]; _HISTORY_CAP=50
SIGNAL_HEADERS=["Symbol","Signal","Entry","SL","TP","RRR","Score","HTF Trend","Status","Telegram","Created UTC"]
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

def mode_rows():
    """Rows for the execution-mode/safety table."""
    return [[k, v] for k, v in mode_snapshot().items()]

def initial_view():
    ensure_worker()
    record_heartbeat("RUNNING")
    return _outputs()+[mode_rows()]
def refresh_signals():
    if not _analysis_lock.acquire(blocking=False):
        s=dashboard_snapshot(); return _outputs(s)+[ "Analysis already running; current data shown.", mode_rows() ]
    try:
        from main import run_analysis_once
        started=time.time(); new=run_analysis_once(); _record_signals(new); closed=monitor_paper_positions()
        note=f"{len(new)} new signal(s); {len(closed)} paper exit(s); {time.time()-started:.1f}s"
    except Exception as exc:
        record_heartbeat("ERROR",last_error=str(exc)); note=f"Refresh failed: {exc}"
    finally:
        _analysis_lock.release()
    return _outputs()+[note, mode_rows()]

def ensure_worker():
    global _worker_started
    with _worker_lock:
        if _worker_started: return
        _worker_started=True
    record_heartbeat("RUNNING")
    threading.Thread(target=run_bot_loop,daemon=True,name="trading-bot-loop").start()


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
    with gr.Accordion("Execution mode and safety",open=True):
        gr.Markdown("LIVE is locked until the paper track record clears the configured minimum and an exact confirmation phrase is typed. Delta Exchange India has no testnet, so LIVE is real money. The kill switch forces PAPER immediately and persists across restarts.")
        mode_row=gr.DataFrame(headers=["Setting","Value"],interactive=False,wrap=True)
        with gr.Row():
            mode_dropdown=gr.Dropdown(choices=["MANUAL","PAPER","LIVE"],value=None,label="Request mode")
            phrase_box=gr.Textbox(label="LIVE confirmation phrase",interactive=True,visible=False)
        with gr.Row():
            apply_mode_button=gr.Button("Apply mode",variant="primary")
            kill_button=gr.Button("ENGAGE KILL SWITCH - FORCE PAPER",variant="stop")
            refresh_mode_button=gr.Button("Refresh mode state")
        with gr.Row():
            release_phrase_box=gr.Textbox(label="Kill switch release phrase",interactive=True)
            release_kill_button=gr.Button("Release kill switch")
        mode_note=gr.Textbox(label="Mode result",interactive=False)
        def on_mode_pick(choice):
            return gr.update(visible=(choice=="LIVE"))
        def apply_mode(choice,phrase):
            ok,msg=request_mode_change(choice,phrase)
            if not ok: record_heartbeat("ERROR",last_error=msg)
            return msg,mode_rows()
        def engage_kill():
            result=engage_kill_switch("dashboard button")
            return f"Kill switch ENGAGED - execution forced to {result['mode']}",mode_rows()
        def release_kill(phrase):
            ok,msg=release_kill_switch(phrase)
            if not ok: record_heartbeat("ERROR",last_error=msg)
            return msg,mode_rows()

        gr.Markdown("Execution remains `PAPER`; OpenAlgo and exchange execution are disabled. The kill switch and daily-loss/open-position limits are enforced before simulated position creation. Engaging the kill switch takes one click; releasing it requires the confirmation phrase, so it cannot be disarmed by accident. Telegram shows configured/not configured; delivery status is recorded per signal.")
    zerogpu_button.click(zerogpu_status,outputs=gpu)
    mode_dropdown.change(on_mode_pick,inputs=mode_dropdown,outputs=phrase_box)
    apply_mode_button.click(apply_mode,inputs=[mode_dropdown,phrase_box],outputs=[mode_note,mode_row])
    kill_button.click(engage_kill,outputs=[mode_note,mode_row])
    release_kill_button.click(release_kill,inputs=release_phrase_box,outputs=[mode_note,mode_row])
    # gr.DataFrame has no .click() event in Gradio 6, so the safety table is
    # refreshed by a button and on page load instead of a click on the table.
    refresh_mode_button.click(mode_rows,outputs=mode_row)
    outputs=[health,metrics,signals,positions,closed,chart,status]
    refresh_button.click(refresh_signals,outputs=outputs+[note,mode_row])
    demo.load(initial_view,outputs=outputs+[mode_row])

if __name__=="__main__":
    ensure_worker()
    demo.launch(theme=gr.themes.Soft(), allowed_paths=ALLOWED_PATHS, show_error=True)

