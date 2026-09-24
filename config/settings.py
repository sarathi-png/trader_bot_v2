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
