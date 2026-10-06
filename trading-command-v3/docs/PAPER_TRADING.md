# Paper trading

Paper mode simulates a full account against real-time market prices without touching
the exchange. Enable it in Settings → Execution (default is READ ONLY).

## Semantics

- **Market orders** fill at the current market price (0.05 % taker fee per side).
- **Limit / stop** orders rest in `paper_orders` and are evaluated lazily against the
  latest prices whenever the dashboard polls — no background process needed.
- Optional **SL/TP brackets** attach to the resulting position and trigger fills at the
  level price.
- Positions net per symbol: same-side adds average in, opposite side reduces and realizes
  P&L; flips are supported.
- Closing a position writes a `trade_journal` row tagged `mode=paper, source=paper` —
  paper records are never mixed with live exchange records.

## Risk limits enforced before acceptance

`maxDailyLoss` (realized today), `maxOrderValue`, `maxOpenPositions` — see Settings → Risk.
Blocked orders are audit-logged as `risk_block_triggered`.

## Separation guarantees

- Paper tables are distinct from any exchange data.
- Journal rows always carry their `mode`.
- Analytics label samples/paper/live distinctly.
