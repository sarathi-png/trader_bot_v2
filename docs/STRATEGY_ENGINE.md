# Strategy engine

The engine is a set of pluggable strategy functions over a shared context
(candles, EMA20/50, swing structure, clustered S/R levels). It only evaluates
**closed candles** — the forming candle is never treated as evidence.

## Market structure

Fractal pivots (window 2) are classified into `HH / HL / LH / LL`. The sequence is
displayed ("HH → HL → …") and combined with EMA alignment:

- `BULLISH` — rising swings + EMA20 > EMA50
- `BEARISH` — falling swings + EMA20 < EMA50
- `RANGE` — mixed swings
- `UNCLEAR` — insufficient evidence

Labels are informational observations, never certainty claims.

## Support / resistance

Swing prices are clustered within `sensitivity × price`; clusters with
≥ `minTouches` become levels, scored by touches and recency (0–100 % confidence shown).
Adjustable in Strategy → Detection Settings.

## Strategies

| id | Logic |
|---|---|
| `trend` | EMA-aligned pullback entries, stop at last swing, 1:2 target |
| `breakout` | closes beyond strongest clustered level, stop back inside |
| `sr` | reaction at strong level filtered by trend |

Each returns `WAIT / WATCH / LONG_SETUP / SHORT_SETUP / INVALIDATED` **plus reasons** —
the UI shows *why*, not just *what*.

## Persistence

Every non-WAIT evaluation is stored in `signals` with outcome lifecycle:
`ACTIVE → SUPERSEDED / EXPIRED / TRIGGERED / INVALIDATED / MANUAL_OVERRIDE`.
Strategy outputs are setups, not predictions; no accuracy claims are made.
