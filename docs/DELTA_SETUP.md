# Delta Exchange India setup

## 1. Create API keys

Delta India app → Profile → **API Management** → Create API Key.
Grant *Read Data* (+ *Trading* only if you intend live execution).
Whitelist your server IP — Delta rejects non-whitelisted signed requests.

## 2. Configure the server

```env
DELTA_API_KEY=your_key
DELTA_API_SECRET=your_secret
```

Restart. Settings → Delta API will show **CONFIGURED**. Secrets are read from the
environment only — never from the browser, database or logs.

## 3. Endpoints used (current docs)

| Purpose | Endpoint |
|---|---|
| Tickers | `GET /v2/tickers` |
| Candles | `GET /v2/history/candles?symbol=&resolution=&start=&end=` |
| Order book | `GET /v2/orderbook?symbol=` |
| Trades | `GET /v2/trades?symbol=` |
| Wallet | `GET /v2/wallet/balances` (auth) |
| Positions | `GET /v2/positions` (auth) |
| Orders | `GET/POST /v2/orders` (auth) |
| Product lookup | `GET /v2/products/{symbol}` |

Authentication for private calls:
`signature = HMAC_SHA256(secret, METHOD + timestamp + path + queryString + body)`,
sent as `api-key`, `timestamp`, `signature` headers. Signatures expire in ~5 s;
the client signs per-request with the current unix time.

## 4. WebSocket

Public socket: `wss://socket.india.delta.exchange`.
The browser subscribes to `v2/ticker` for watched symbols (no credentials).
Private channels (`orders`, `positions`, `fill`) require `key-auth`
(`HMAC(secret, "GET" + ts + "/live")`) and are consumed server-side in a future iteration;
today private data flows through authenticated REST.

## Rate limits

All market responses are cached 2–10 s server-side; polls are throttled so a single
dashboard stays far below Delta's limits. HTTP 429 is surfaced as "rate limited" in the UI.
