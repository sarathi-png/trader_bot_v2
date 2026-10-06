# Architecture

```
Delta Exchange India (REST + public WS)
        │                       │
        ▼                       ▼
 Market adapter (src/lib/market)   Browser public WS overlay (tickers only, no credentials)
   ├─ delta.ts   signed REST client
   ├─ demo.ts    deterministic simulator (labelled)
   └─ service.ts facade + TTL caches
        │
        ▼
 Next.js API routes (src/app/api/*)  ← single trusted boundary
        │
        ├─ Strategy engine (src/lib/strategy) → signals table
        ├─ Paper engine (src/lib/paper) → paper_orders / paper_positions / journal
        ├─ Risk limits (checked before every paper/live order)
        └─ Settings / drawings / alerts / audit (PostgreSQL via Drizzle)
        │
        ▼
 Browser: Zustand stores + poll/WS merge → Lightweight Charts + drawing overlay
```

## Principles

- **No TradingView dependency.** The dashboard receives data, renders candles and detects
  setups itself. TradingView webhooks are an optional, disabled-by-default receiver.
- **Private credentials never leave the server.** The browser only talks to our own API
  routes (and Delta's *public* ticker socket, which requires no auth).
- **Demo ≠ live.** Every market object carries `source: "demo" | "delta"`; the UI labels
  demo data and shows N/A (never fabricated zeros) for unsupported fields.
- **Execution is a progression:** READ ONLY → PAPER → LIVE, each gated independently.
- **Honest states:** failures surface as readable messages ("Delta market-data connection
  was interrupted"), stale/labelled fallbacks are never silent.

## Key tables

`settings`, `drawings`, `signals`, `trade_journal`, `paper_orders`, `paper_positions`,
`alert_rules`, `audit_log`.

## Real-time model

Ticker polling (2.6 s) + optional Delta `v2/ticker` WebSocket overlay; candles polled per
chart timeframe (5 s); paper TP/SL & resting orders evaluated lazily on each poll — no
background workers required for MVP.
