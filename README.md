# Trading Command

A private, personal trading intelligence terminal: Delta Exchange India market data,
TradingView Lightweight Charts rendering, a modular strategy/signal engine, risk tooling,
paper trading and a trade journal — in one dark, low-clutter workspace.

It is **not** a TradingView/Delta/OSIRIS clone. It is a personal command center that answers:
*Where is price? What is the market doing? What is my setup? What is my position? What is my risk?*

## Quick start

```bash
npm install
cp .env.example .env          # defaults run fully in demo mode
npx drizzle-kit push          # create tables
npm run dev
```

Open the app, complete the 5-step onboarding, done. Without any Delta credentials the
workspace runs on a **clearly-labelled deterministic demo simulator** (candles print live
as time advances).

## Modes (progression of trust)

| Mode | What it does | How to reach it |
|---|---|---|
| **READ ONLY** (default) | Data, analysis, journal. No order entry. | Default |
| **PAPER** | Simulated orders/positions vs live-style prices, risk limits enforced, auto-journalled | Settings → Execution |
| **LIVE** | Order routing to Delta — only with `LIVE_EXECUTION_ENABLED=true`, LIVE mode **and** the master switch armed | Env + Settings |

## Delta Exchange India

- Public data (tickers/candles/order book) needs **no credentials** — set data source to
  "Delta Exchange India" in Settings → Market Data.
- Private account data & live orders require `DELTA_API_KEY` / `DELTA_API_SECRET` in the
  server environment. Keys never reach the browser, database or logs.
- See `docs/DELTA_SETUP.md`.

## Feature flags

All sensitive capabilities default OFF: `LIVE_EXECUTION_ENABLED`, `TRADINGVIEW_WEBHOOK_ENABLED`,
`TELEGRAM_ENABLED`. Paper trading, strategy engine, order book and auto-S/R default ON but can
be disabled. Full list in `.env.example`.

## Documentation

- `docs/ARCHITECTURE.md` — data flow, event model, module map
- `docs/DELTA_SETUP.md` — API keys, endpoints used, WebSocket channels
- `docs/STRATEGY_ENGINE.md` — strategies, structure & S/R detection
- `docs/PAPER_TRADING.md` — paper engine semantics
- `docs/WEBHOOKS.md` — optional TradingView webhook (disabled by default)
- `docs/SECURITY.md` — secrets handling, safety gates
- `docs/DEPLOYMENT.md` — local, Docker, Cloudflare Tunnel

## Keyboard

`Ctrl/⌘+K` command palette · `1/3/5/M/H/D` timeframes · `C` chart · `P` positions ·
`J` journal · `A` alerts · `?` all shortcuts.

## Attribution

Charting rendered by [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/)
(Apache-2.0). Market data courtesy Delta Exchange India.
