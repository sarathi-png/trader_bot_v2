# Security model

## Secrets

- `DELTA_API_KEY` / `DELTA_API_SECRET` live **only** in the server environment.
- No credential input fields exist in the UI; nothing is stored in the database,
  localStorage or logs, and no secret is ever shipped to the browser bundle.
- Audit log entries never contain keys or signatures.

## Authentication

Every route under `/api` is authenticated by `middleware.ts`, so a route added
later cannot forget to check.

Two credentials are accepted:

- a signed session cookie (`tc_session`, HttpOnly, SameSite=Strict, 12h), issued
  by `POST /api/auth/login` with `{"password": "..."}`
- `Authorization: Bearer <API_PASSWORD>` for scripts and smoke tests

The password is compared in constant time, and the cookie is an HMAC-SHA256
signature over its own expiry verified with `crypto.subtle.verify`.

**Fail closed.** With no `API_PASSWORD` configured the API returns `503` on every
protected route rather than serving it unauthenticated. Set `API_PASSWORD` (and a
separate `SESSION_SECRET`) before adding Delta credentials.

Exempt routes: `/api/auth/login`, `/api/auth/logout`, `/api/health`, and the
TradingView webhook — which carries its own shared-secret auth.

## Execution gates (all must pass for a live order)

1. `LIVE_EXECUTION_ENABLED=true` (environment)
2. `settings.mode === "live"` (user action, confirm dialog)
3. `settings.liveArmed === true` (master switch, server-verified confirmation token)
4. Delta credentials configured

Every gate failure returns HTTP 403 and is audit-logged (`live_order_rejected`).

## Risk layer

`src/lib/risk.ts` holds the single implementation used by **both** the paper
engine and the live order route, so the two cannot drift. An order is blocked
before submission, and the block is audit-logged as `risk_block_triggered`,
when any of these fail:

| Limit | Check |
|---|---|
| `maxOrderValue` | `qty × price` above the cap |
| `maxDailyLoss` | realised P&L since UTC midnight at or below `-limit` |
| `maxOpenPositions` | opening a **new** symbol at the cap (adding to an existing one is allowed) |
| `maxLeverage` | `(existing notional + order value) / equity` above the cap |

Limits are re-normalised on every evaluation (`normalizeRiskLimits`), so a
nonsense value written into settings cannot disable a cap.

**Unknown daily P&L blocks trading.** `evaluateOrderRisk` takes
`dailyRealizedPnl: number | null`; `null` means "cannot be verified" and refuses
the order. `liveRealizedPnlToday()` currently returns `null`, so **live orders
remain closed** until it reads real fills from the exchange. A daily-loss limit
that silently assumes zero loss is not a limit.

## Order idempotency

Every live order carries a `client_order_id` (supplied by the caller or
generated). It is written to `live_orders` with a unique constraint **before**
submission, so a retried request finds the existing row and returns the original
result (`deduplicated: true`) instead of placing a second order.

Status moves `pending → submitted | failed`, and `delta_order_id` is retained for
reconciliation.

## Webhook hardening

Disabled by default; shared-secret auth; ±5 min timestamp window; per-payload dedupe;
30 req/min limit; signals-only (no execution).

## Transport / deployment

Run behind HTTPS (reverse proxy or Cloudflare Tunnel). Keep Postgres bound to
localhost/private network — never expose port 5432. Set CORS/proxy rules so only your
dashboard origin reaches the API.

## Data integrity

Every market object carries `source` and timestamps; stale data is labelled, never
silently substituted. Demo data can never masquerade as live.
