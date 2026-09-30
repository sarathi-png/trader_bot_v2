"""
Application configuration settings for Trading Bot v2.
Loads environment variables and defines default trading parameters.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
load_dotenv(Path(__file__).parent.parent / ".env")


# ─── Ticker Universe ─────────────────────────────────────────────────────────
TICKERS = {
    "crypto": ["BTC/USDT"],
    "stocks": ["AAPL"],
    "forex": ["EURUSD=X"],
}

# Flattened list for iteration
ALL_TICKERS = []
for _assets in TICKERS.values():
    ALL_TICKERS.extend(_assets)


# ─── Timeframe Settings ──────────────────────────────────────────────────────
HTF = "1h"   # Higher timeframe for trend bias
LTF = "15m"  # Lower timeframe for entry signal


# ─── Risk Management Defaults ────────────────────────────────────────────────
RISK_PCT: float = float(os.getenv("ACCOUNT_RISK_PCT", "1.0"))  # % of account per trade
MIN_RRR: float = 2.0          # Minimum reward-to-risk ratio
ATR_MULT: float = 1.5         # ATR multiplier for stop-loss distance
N_SWING: int = 5              # Swing lookback window


# ─── Technical Indicator Settings ─────────────────────────────────────────────
ATR_PERIOD: int = 14           # ATR lookback period
MA_FAST: int = 9               # Fast MA period (optional crossover)
MA_SLOW: int = 21              # Slow MA period (optional crossover)


# ─── Telegram Configuration ──────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")


# ─── Exchange Configuration ──────────────────────────────────────────────────
EXCHANGE_NAME: str = os.getenv("EXCHANGE_NAME", "yahoo")
ACCOUNT_BALANCE: float = float(os.getenv("ACCOUNT_BALANCE", "10000.0"))


# ─── Paths ───────────────────────────────────────────────────────────────────
PROJECT_OUTPUT_DIR = Path(__file__).parent.parent / "output"
PROJECT_OUTPUT_DIR.mkdir(exist_ok=True)

# Hugging Face Spaces can mount persistent storage at /data. Environment
# overrides (DATA_DIR, DB_PATH, CHART_DIR) remain available for other hosts.
_runtime_data_dir = os.getenv("DATA_DIR")
if not _runtime_data_dir:
    _runtime_data_dir = "/data" if os.getenv("SPACE_ID") and Path("/data").is_dir() else str(PROJECT_OUTPUT_DIR)
OUTPUT_DIR = Path(_runtime_data_dir)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
CHART_DIR = Path(os.getenv("CHART_DIR", str(OUTPUT_DIR / "charts")))
CHART_DIR.mkdir(parents=True, exist_ok=True)


# ─── S/R Zone Clustering ────────────────────────────────────────────────────
ZONE_TOLERANCE_PCT: float = 0.003  # 0.3% tolerance for zone clustering
TRENDLINE_LOOKBACK: int = 30       # Candles for trendline regression
TRENDLINE_MIN_SWINGS: int = 3      # Minimum swings for valid trendline

# ─── v3 operations / persistence ─────────────────────────────────────────────
SCAN_INTERVAL_MINUTES = int(os.getenv("SCAN_INTERVAL_MINUTES", "15"))
SCHEDULE_OFFSET_SECONDS = int(os.getenv("SCHEDULE_OFFSET_SECONDS", "5"))
DEDUPE_ENABLED = os.getenv("DEDUPE_ENABLED", "true").lower() == "true"
MAX_DAILY_LOSS_PCT = float(os.getenv("MAX_DAILY_LOSS_PCT", "3.0"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MAX_POSITION_PCT = float(os.getenv("MAX_POSITION_PCT", "25.0"))
# ─── Stage 4: execution mode + LIVE safety gates ─────────────────────────────
# EXECUTION_MODE accepts MANUAL | PAPER | LIVE (anything else falls back to
# PAPER). LIVE is NOT switchable by editing this file alone: it additionally
# requires a runtime confirmation phrase and a passing paper track record
# (see execution/modes.py and operations.live_gate_report).
#
# The thresholds below are deliberately demanding. Delta Exchange India has
# no testnet, so LIVE always means real money. Raise them, never lower.
LIVE_MIN_PAPER_TRADES = int(os.getenv("LIVE_MIN_PAPER_TRADES", "200"))
LIVE_MIN_WIN_RATE_PCT = float(os.getenv("LIVE_MIN_WIN_RATE_PCT", "45"))
# Exact phrase a human must type to arm LIVE at runtime.
LIVE_CONFIRM_PHRASE = os.getenv("LIVE_CONFIRM_PHRASE", "ENABLE LIVE TRADING")
# Optional belt-and-braces env kill switch, honoured alongside the runtime one.
KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() == "true"
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER").upper()
DB_PATH = Path(os.getenv("DB_PATH", str(OUTPUT_DIR / "trading_bot_v3.db")))

# Taker fee verified from Delta's own help article "How is the Trading Fee
# for Futures Contract Calculated" (fetched 2026-09-29): maker 0.02%, taker
# 0.05% of notional. Delta also states "18% GST is applicable on trading
# fees", so a taker fill really costs 0.05% * 1.18 = 0.059% per side. The
# previous 0.10% was an unsourced guess that overcharged each side by ~1.7x.
# Funding payments are NOT modelled here (see walk-forward caveats).
PAPER_FEE_PCT = float(os.getenv("PAPER_FEE_PCT", "0.059"))
PAPER_SLIPPAGE_PCT = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.02"))
OPENALGO_URL = os.getenv("OPENALGO_URL", "")
OPENALGO_API_KEY = os.getenv("OPENALGO_API_KEY", "")
OPENALGO_ENABLED = os.getenv("OPENALGO_ENABLED", "false").lower() == "true"

# ─── Stage 1: market data source + quality gates ────────────────────────────
# DATA_SOURCE=DELTA routes crypto candles through Delta Exchange India's
# public REST API (real exchange data, no yfinance lag) with yfinance kept
# as automatic fallback. Set DATA_SOURCE=YAHOO to disable Delta entirely.
DATA_SOURCE: str = os.getenv("DATA_SOURCE", "DELTA").upper()  # DELTA | YAHOO
DELTA_BASE_URL: str = os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange")
DELTA_MAX_RPS: float = float(os.getenv("DELTA_MAX_RPS", "5"))

# Quality gates: skip a scan for a symbol when its newest candle is older
# than (max_age_bars + 1) bar intervals, or top-of-book spread is unusable.
DATA_STALE_MAX_BARS: int = int(os.getenv("DATA_STALE_MAX_BARS", "2"))
MAX_SPREAD_PCT: float = float(os.getenv("MAX_SPREAD_PCT", "0.5"))

# ─── Stage 2: signal quality / confluence gate ───────────────────────────────
# Every candidate signal gets a 0-100 multi-TF confluence score
# (engine/confluence.py). Signals below CONFLUENCE_MIN_SCORE (measured on
# their own side: a SHORT at 30 is as strong as a LONG at 70) are dropped,
# and a score pointing the opposite way vetoes the trade outright.
CONFLUENCE_ENABLED = os.getenv("CONFLUENCE_ENABLED", "true").lower() == "true"
CONFLUENCE_MIN_SCORE = float(os.getenv("CONFLUENCE_MIN_SCORE", "55"))
CONFLUENCE_VETO_OPPOSITE = os.getenv("CONFLUENCE_VETO_OPPOSITE", "true").lower() == "true"
CONFLUENCE_DIRECTION_THRESHOLD = float(os.getenv("CONFLUENCE_DIRECTION_THRESHOLD", "0.15"))

# Component weights (normalized automatically; sum need not be 1).
CONFLUENCE_W_TREND: float = float(os.getenv("CONFLUENCE_W_TREND", "0.35"))
CONFLUENCE_W_ZONE: float = float(os.getenv("CONFLUENCE_W_ZONE", "0.25"))
CONFLUENCE_W_MOMENTUM: float = float(os.getenv("CONFLUENCE_W_MOMENTUM", "0.25"))
CONFLUENCE_W_VOLUME: float = float(os.getenv("CONFLUENCE_W_VOLUME", "0.15"))

# HTF EMA pair used for trend bias (swing structure uses N_SWING).
CONFLUENCE_EMA_FAST: int = int(os.getenv("CONFLUENCE_EMA_FAST", "20"))
CONFLUENCE_EMA_SLOW: int = int(os.getenv("CONFLUENCE_EMA_SLOW", "50"))
