# Vercel environment checklist — Trading Command v3

All variables below are configured as **Production → Secret** in the Vercel
project `sarathi-pngs-projects/trading-command-v3` (set via
`vercel env add <NAME> production`, values taken from the local `.env`,
never committed).

## Set (14)

| Name | Purpose | Notes |
|------|---------|-------|
| `API_PASSWORD` | Operator login for every `/api` route | Unset ⇒ routes return 503 (fail-closed) |
| `SESSION_SECRET` | Signs the session cookie | Deliberately different from `API_PASSWORD` |
| `DELTA_API_KEY` | Delta Exchange India key (read-only use) | Server-side only, never in responses |
| `DELTA_API_SECRET` | Delta Exchange India secret | Same |
| `DELTA_MARKET_ENABLED` | Live market data via Delta REST | `true` |
| `LIVE_EXECUTION_ENABLED` | Order placement | **`false`** — keep off until you intend live trading |
| `PAPER_TRADING_ENABLED` | Paper execution | `true` |
| `STRATEGY_ENGINE_ENABLED` | Strategy + quant evaluation routes | `true` |
| `ORDERBOOK_ENABLED` | L2 orderbook panel | `true` |
| `AUTO_S_R_ENABLED` | Automatic S/R detection | `true` |
| `JOURNAL_ENABLED` | Trade journal module | `true` |
| `ANALYTICS_ENABLED` | Analytics module | `true` |
| `TELEGRAM_ENABLED` | Telegram notifications | `false` |
| `TRADINGVIEW_WEBHOOK_ENABLED` | TradingView webhook receiver | `false` |

## Deliberately NOT set

- `DATABASE_URL` — **removed**: it pointed at a local Postgres Vercel cannot
  reach. v3 now runs on the file-backed store (`src/lib/fileStore.ts`) and
  falls back automatically. To persist across deployments on Vercel, either
  attach Vercel Postgres/Neon and set `DATABASE_URL`, or set:
  - `HF_TOKEN` — fine-grained token with write access
  - `HF_DATASET_ID=<user>/TC-state` — an empty Dataset repo
    (enables `src/lib/hfSync.ts`, the same pattern as the Python bot)
- `USD_INR_RATE` — app defaults to `83`; set it if the rate drifts
- `TRADINGVIEW_WEBHOOK_SECRET`, `DELTA_REST_BASE`, `DELTA_WS_URL` — defaults
  are correct (`https://api.india.delta.exchange`, `wss://socket.india.delta.exchange`)

## Rotating secrets after a leak

```powershell
vercel env rm API_PASSWORD production --yes
vercel env add API_PASSWORD production     # paste the new value, Ctrl+Z
```

## Redeploy after changing env vars

```powershell
vercel deploy --prod --yes
```
