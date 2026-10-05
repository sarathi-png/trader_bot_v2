# TradingView webhooks (optional, disabled by default)

Endpoint: `POST /api/integrations/tradingview/webhook`

**Disabled unless** `TRADINGVIEW_WEBHOOK_ENABLED=true`. Even enabled, it **never places
orders** — it converts validated alerts into internal Signal rows for review.

## Pipeline

```
webhook → secret check → timestamp freshness (±5 min) → payload validation
        → dedupe (symbol+action+ts) → insert Signal → audit log
```

## Enabling

```env
TRADINGVIEW_WEBHOOK_ENABLED=true
TRADINGVIEW_WEBHOOK_SECRET=a-long-random-string
```

Request requirements:

```json
{
  "symbol": "BTCUSD",
  "action": "LONG",          // LONG | SHORT | CLOSE | WATCH
  "timeframe": "15m",
  "price": 108000,
  "strategy": "breakout",
  "timestamp": 1730000000000
}
```

Send the secret in the `x-webhook-secret` header (or `secret` field). Rate limit:
30 req/min. Rejected calls are audit-logged.

## Important

TradingView can only emit webhooks if your TradingView plan includes alert webhooks.
A Cloudflare Tunnel exposes *this* service — it cannot substitute for a TradingView
subscription. The dashboard does not depend on webhooks at all.
