---
title: Trading Bot v3
emoji: 📈
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: "6.15.1"
app_file: app.py
python_version: "3.10"
pinned: false
---
# Trading Bot v3

A multi-asset trading bot for crypto, stocks, and forex with signal generation, risk management, and Telegram alerts.

## Features

- **Multi-Asset Support:** BTC/USDT, AAPL, EURUSD (extensible)
- **Dual Timeframe Analysis:** HTF (1h) trend bias + LTF (15m) entry signals
- **S/R Zone Detection:** Swing point clustering with automatic zone identification
- **ATR-Based Risk Management:** Dynamic SL/TP with reward-to-risk validation
- **Chart Generation:** Annotated candlestick charts with mplfinance
- **Telegram Alerts:** Real-time signal delivery with charts and formatted captions
- **Manual Mode:** No auto-execution — all trades require manual confirmation

## Quick Start

### 1. Clone and Install

```bash
git clone <repo-url>
cd trading-bot-v2
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Edit `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
EXCHANGE_NAME=binance
ACCOUNT_RISK_PCT=1.0
```

### 3. Run Locally

```bash
# Single execution (manual mode)
python main.py

# Continuous loop (every 15 minutes)
TRADING_BOT_LOOP=true python main.py
```

## Deploy to HuggingFace Spaces

### 1. Create HF Account
- Go to [huggingface.co](https://huggingface.co)
- Create a new Space with Gradio SDK

### 2. Push Code

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://huggingface.co/spaces/YOUR_USERNAME/trading-bot-v2
git push -u origin main
```

### 3. Add Secrets
In your HF Space settings:
- Go to **Settings** → **Repository secrets**
- Add: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, etc.

### 4. The app.py
The Gradio interface (`app.py`) runs on the Space (ZeroGPU `zero-a10g` hardware, CPU-only workload) with a background thread executing the strategy every 15 minutes.

## Architecture

```
trading-bot-v2/
├── config/
│   ├── settings.py          # Configuration and environment variables
│   └── .env.example         # Template for secrets
├── data/
│   └── streamer.py          # CCXT data fetching with yfinance fallback
├── engine/
│   ├── indicators.py        # ATR, MA crossover, RSI
│   ├── sr_zones.py          # Support/resistance zone detection
│   ├── trendlines.py        # Linear regression trendlines
│   └── risk_engine.py       # SL/TP calculation and position sizing
├── charting/
│   └── plotter.py           # mplfinance chart generation
├── alerts/
│   └── telegram.py          # Telegram Bot API integration
├── execution/
│   └── broker.py            # Paper trading stub (manual mode)
├── main.py                  # Entry point and orchestration
├── app.py                   # Gradio interface for HF Spaces
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

## Deployment Notes (HuggingFace Space)

The Space runs on **ZeroGPU (`zero-a10g`)**, the only hosting tier available to
free personal accounts for Gradio Spaces. Consequences:

- `app.py` must `import spaces` and bind at least one `@spaces.GPU`-decorated
  function to a Gradio event, otherwise startup fails with
  `RuntimeError: No @spaces.GPU function detected during startup`.
  The "Check ZeroGPU slot" button is that handler; the trading logic itself is CPU-only.
- `sdk_version` in this file must match the `gradio` pin in `requirements.txt`
  (currently gradio 6.x). gradio 4.x is not usable here: it imports
  `huggingface_hub.HfFolder` (removed in hub 1.x) and crashes with modern
  starlette/jinja2 (`TypeError: unhashable type: 'dict'`).
- Charts are rendered with the non-interactive `Agg` matplotlib backend
  (no display inside the container).
- Add `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` as Space secrets to receive alerts.

## Signal Logic

1. **BUY Signal:** Price within 0.5×ATR of support zone + HTF uptrend/ranging
2. **SELL Signal:** Price within 0.5×ATR of resistance zone + HTF downtrend/ranging

### Risk Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| RISK_PCT | 1.0% | Account risk per trade |
| MIN_RRR | 2.0 | Minimum reward-to-risk ratio |
| ATR_MULT | 1.5 | ATR multiplier for SL distance |
| N_SWING | 5 | Swing point lookback window |

## Manual Execution Flow

⚠️ **This bot does NOT auto-execute trades.**

1. Bot generates signal and sends to Telegram
2. Review the chart and signal details
3. Open your exchange (Binance, etc.)
4. Manually enter the order with the provided SL/TP levels
5. Monitor the position

## License

MIT


## v3 operations and safety

v3 persists analysis runs, signals, and paper orders in `output/trading_bot_v3.db`. Signals are deduplicated by symbol, timeframe, direction, and source candle. The default `EXECUTION_MODE=PAPER` never submits live orders. `KILL_SWITCH=true` stops analysis.

The scheduler is aligned to the configured scan interval with a small offset. For production use, run the bot on a persistent host rather than relying on a Gradio Space process. Configure secrets in the host's environment or HF Space secrets; do not commit `.env` files.

Recommended progression: paper mode, backtest, OpenAlgo Analyzer Mode, broker sandbox, then small supervised live orders. Do not enable live execution until idempotency, portfolio limits, SL/TP handling, and broker reconciliation are implemented and tested.


## v3 Operations Dashboard

The Space now exposes persisted bot health, 24-hour run counts, signals-today count, paper positions, closed trades, realized P&L, configured position limits, execution mode, kill-switch state, Telegram configuration, and OpenAlgo state. The background worker aligns scans to the configured post-close offset, records a durable heartbeat, monitors paper SL/TP levels, and prevents overlapping manual/background analyses.

Paper orders use risk-based sizing constrained by `MAX_POSITION_PCT`, the kill switch, `MAX_OPEN_POSITIONS`, and `MAX_DAILY_LOSS_PCT`. Slippage and fees are percentage values (for example `0.02` means 0.02%). Real exchange execution remains unavailable.

## Signal persistence on Hugging Face

Hugging Face container files are ephemeral unless persistent storage is enabled. In the Space settings, open **Settings → Storage** and enable **Persistent Storage**. The mounted directory is `/data`. The application automatically uses `/data/trading_bot_v3.db` and `/data/charts` when running in a Space with that mount; local development continues to use `output/`.

`DATA_DIR`, `DB_PATH`, and `CHART_DIR` can override these paths. The dashboard's **Storage** metric shows the active database path. Signals already delivered to Telegram cannot be recovered through Telegram's Bot API after the old ephemeral database is gone, but future signals will survive Space rebuilds when persistent storage is enabled.

## Telegram private chat and group setup

`TELEGRAM_CHAT_ID` is the destination for generated signal charts. It works for either a private chat or a group:

1. In the Space settings, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository secrets.
2. For a private chat, use the numeric chat ID returned by a trusted bot such as `@userinfobot`.
3. For a group, add your bot to the group, allow it to send photos/messages, and use the group's numeric ID, which normally starts with `-` (for example `-1001234567890`). A bot ID or group username is not a valid `chat_id` for the Bot API.
4. If the bot only needs to broadcast signals, privacy mode does not block outgoing photos. If you later add commands such as `/status`, configure the bot through `@BotFather` and give it appropriate group permissions.
5. Restart/redeploy the Space after changing secrets. The dashboard shows **Telegram: Configured** only when both the token and destination chat ID are present; each signal separately records `SENT`, `FAILED`, or `NOT_CONFIGURED`.

## Validation

Run the repeatable v3 checks with:

```bash
python -m unittest discover -s tests -v
```

## v3 paper execution and OpenAlgo guard

Signals in `EXECUTION_MODE=PAPER` now create durable simulated positions in the SQLite store. The paper engine supports fees, configurable slippage, local SL/TP checks, realized P&L, and daily P&L tracking. `execution/openalgo.py` is disabled by default; it refuses `place_order` unless `OPENALGO_ENABLED=true` and URL/API key configuration are present. It is a guard/scaffold, not a live trading recommendation.
