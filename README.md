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
python Scripts/run_tests.py tests.test_confluence tests.test_data_pipeline tests.test_modes tests.test_v3
```

## Strategy validation status (2026-09-29) — LIVE is not justified

Walk-forward validation over deep, paginated Delta history (no keys, read-only)
says the current confluence gate has **no gross edge**, so no amount of
threshold tuning makes it tradable. Do not move `EXECUTION_MODE` to `LIVE`.

| Sample | LTF/HTF | Bars | Trades | avg R (cost-free) | avg net P&L | Profit factor |
|---|---|---|---|---|---|---|
| 208 days | 15m / 1h | 20,000 | 1,409 | **+0.009** | −0.150% | 1.01 |
| 499 days | 1h / 4h | 12,000 | 787 | **−0.025** | −0.206% | 0.96 |

avg R of ±0.01–0.03 is zero, not a suppressed edge: round-trip cost is 0.158%
(2 × 0.059% taker incl. GST + 2 × 0.02% slippage) and measured net is −0.150%,
which implies gross ≈ +0.008%. Folds are now *consistent* (PF 0.91–1.17) — the
wild 2.67 / 0.36 swing seen in the original 10-day / 1,000-bar sample was
small-sample noise, and the earlier "positive gross P&L" reading did not survive
a real sample.

An information-coefficient scan (`Scripts/run_signal_diagnostic.py`, 11,750
decisions) explains why. Spearman rank correlation of each signed component
against forward return:

| predictor | +4b | +16b | +48b |
|---|---|---|---|
| score_signed | −0.013 | −0.011 | −0.002 |
| trend | +0.008 | +0.015 | −0.002 |
| zone | +0.004 | −0.007 | +0.019 |
| momentum | **−0.053** | **−0.051** | −0.007 |
| volume | −0.029 | −0.024 | +0.002 |

Every component is ≈ 0, and the strongest one — momentum — is **inverted**:
on this sample it predicts the *opposite* direction (mean reversion scored as
continuation). A weighted sum of four zero-information inputs, one of them
mis-signed, cannot produce positive expectancy.

The obvious "just flip the mis-signed component" rescue was tested and does not
work (same 124-day window, ~871 trades, weights overridden via env):

| Variant | avg R | avg net P&L |
|---|---|---|
| Baseline weights | +0.029 | −0.139% |
| Invert `momentum` only | +0.004 | −0.153% |
| Invert all four components | +0.029 | −0.139% |

Inverting all four returns *identical* numbers because negating every weight
flips each LONG into its mirror SHORT, and the ATR stop plus 2R target with
symmetric costs are symmetric — so full inversion is a no-op by construction.
Inverting `momentum` alone is actively worse. There is no sign typo to fix.

Reproduce with:

```bash
python Scripts/run_walk_forward.py 15m 1h 20000     # caches history under output/
python Scripts/run_walk_forward.py 1h 4h 12000
python Scripts/run_signal_diagnostic.py 15m 12000
```

History is cached as CSV, so a re-run costs no API requests; pass `--fresh` to
re-pull. Unmodelled: perpetual funding payments, and the stop-first intrabar
assumption is conservative.

### Corrections made while validating

- **Page cap was self-imposed, not an API limit.** `MAX_CANDLE_LIMIT` was 1000,
  which silently capped every backtest at ~10 days. The endpoint really caps at
  4,000 bars/request and `start`/`end` paginate cleanly (13,000 bars stitched
  with zero duplicate timestamps and zero gaps). `fetch_history()` now walks the
  window backwards; 15m history reaches ~2 years, daily ~2.8 years.
- **Fee was an unsourced guess.** `PAPER_FEE_PCT` was 0.10%/side. Delta's own
  help article states maker 0.02% / taker 0.05% of notional, and 18% GST applies
  to fees, so an honest taker fill is 0.059%/side. Correcting it improved
  expectancy by 0.08%/trade and it is *still* negative.
- **The simulator was O(n·m)** (`htf[htf.index < ts]` per bar), so it physically
  could not run past a few thousand bars. `np.searchsorted` replaced the mask;
  `test_htf_window_matches_strictly_before_mask` pins the equivalence.

OpenAlgo is still not implemented.

## v3 paper execution and OpenAlgo guard

Signals in `EXECUTION_MODE=PAPER` now create durable simulated positions in the SQLite store. The paper engine supports fees, configurable slippage, local SL/TP checks, realized P&L, and daily P&L tracking. `execution/openalgo.py` is disabled by default; it refuses `place_order` unless `OPENALGO_ENABLED=true` and URL/API key configuration are present. It is a guard/scaffold, not a live trading recommendation.
