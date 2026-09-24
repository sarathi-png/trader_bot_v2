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
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
CHART_DIR = OUTPUT_DIR / "charts"
CHART_DIR.mkdir(exist_ok=True)


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
KILL_SWITCH = os.getenv("KILL_SWITCH", "false").lower() == "true"
EXECUTION_MODE = os.getenv("EXECUTION_MODE", "PAPER").upper()
DB_PATH = OUTPUT_DIR / "trading_bot_v3.db"

PAPER_FEE_PCT = float(os.getenv("PAPER_FEE_PCT", "0.1"))
PAPER_SLIPPAGE_PCT = float(os.getenv("PAPER_SLIPPAGE_PCT", "0.02"))
OPENALGO_URL = os.getenv("OPENALGO_URL", "")
OPENALGO_API_KEY = os.getenv("OPENALGO_API_KEY", "")
OPENALGO_ENABLED = os.getenv("OPENALGO_ENABLED", "false").lower() == "true"
