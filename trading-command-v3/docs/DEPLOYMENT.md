# Deployment

## Local development (Windows / macOS / Linux)

```bash
npm install
npx drizzle-kit push
npm run dev
```

PostgreSQL must be running (see `DATABASE_URL` in `.env`).

## Production build

```bash
npm run build
npm start
```

Node ≥ 20. The app binds to port 3000 by default (`PORT` env to change).

## Docker

```bash
docker compose up -d
```

Services: `web` (this app) + `postgres`. Redis is intentionally not required for MVP —
the server uses short-TTL in-memory caches. Add Redis later only if you scale the
WebSocket fan-out or add job queues.

## Cloudflare Tunnel (optional remote access)

1. `cloudflared tunnel create trading-command`
2. Route DNS: `cloudflared tunnel route dns trading-command dashboard.example.com`
3. Config:

```yaml
tunnel: <TUNNEL_ID>
ingress:
  - hostname: dashboard.example.com
    service: http://localhost:3000
  - service: http_status:404
```

4. `cloudflared tunnel run trading-command`

The tunnel exposes **your** dashboard over HTTPS. It does not (and cannot) provide
TradingView webhook capability — that depends on TradingView itself. Never expose the
database port through the tunnel.

## Automated checks

Run `npm test` from the project root. It compiles and runs the quant tests, builds
the production app, and exercises login plus the paper-order/journal flow against
an isolated local file store. The smoke test uses demo prices and does not
contact Delta or enable live execution.

## Checklist

- [ ] `LIVE_EXECUTION_ENABLED=false` until you truly need it
- [ ] Delta API key IP-whitelisted
- [ ] HTTPS enforced
- [ ] Postgres not publicly reachable
- [ ] `.env` excluded from git and backups encrypted
