"""
Walk-forward validation of the confluence gate (Stage 2).

Event-driven simulation over closed candles with strict no-look-ahead
rules:

  * The decision at LTF bar i sees ONLY df_ltf[i-window+1 : i+1] and the
    HTF bars whose open time is strictly before the open time of bar i
    (i.e. fully closed HTF bars), each capped to a trailing 200-bar
    window exactly like the live fetch (limit=200).
  * Entry happens at the NEXT bar's open (i+1) with paper-engine
    slippage; intrabar stop/TP scanning assumes stop-first (worst case)
    when both levels sit inside one bar.
  * One position at a time; the scan resumes at the bar after the exit.
  * Costs mirror execution/paper_engine.py: fee_pct per side on the
    notional, adverse slippage on both fills.

walk_forward() splits the simulated trades into chronological folds and
also sweeps score thresholds, so a threshold is only trusted when it
holds up across every fold (the real "validation" for a parameterless
system like this: calibration stability, not curve fitting).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from engine.confluence import ConfluenceConfig, ConfluenceReport, analyze_confluence


def _paper_costs(name: str, fallback: float) -> float:
    from config import settings
    return float(getattr(settings, name, fallback))


def _paper_fee_pct() -> float:
    return _paper_costs("PAPER_FEE_PCT", 0.059)


def _paper_slippage_pct() -> float:
    return _paper_costs("PAPER_SLIPPAGE_PCT", 0.02)


@dataclass(frozen=True)
class BacktestConfig:
    window: int = 200            # bars visible per decision (matches live limit=200)
    warmup: int = 120            # bars consumed before the first decision
    min_score: float = 0.0       # gate inside simulate; threshold sweep happens later
    atr_mult: float = 1.5        # mirrors ATR_MULT
    min_rrr: float = 2.0         # mirrors MIN_RRR
    max_hold_bars: int = 48      # time-stop (12h on 15m) when neither level hits
    # Costs are pulled from settings rather than duplicated here: the last
    # review found the hard-coded 0.1 had drifted from the verified Delta
    # taker fee. Mirror the live paper engine by construction.
    fee_pct: float = field(default_factory=_paper_fee_pct)
    slippage_pct: float = field(default_factory=_paper_slippage_pct)
    folds: int = 4
    threshold_sweep: List[float] = field(default_factory=lambda: [50, 55, 60, 65, 70])


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str                    # LONG | SHORT
    entry: float                 # raw bar open (pre-slippage)
    fill_entry: float
    exit_raw: float
    fill_exit: float
    sl: float
    tp: float
    score: float
    exit_reason: str             # STOP_LOSS | TAKE_PROFIT | TIME_STOP
    pnl_pct: float               # net of fees+slippage, on entry notional
    r_multiple: float            # price R, cost-free


def _decide(ltf_win: pd.DataFrame, htf_win: pd.DataFrame,
            cfg: ConfluenceConfig) -> ConfluenceReport:
    return analyze_confluence(ltf_win, htf_win, cfg)


def _levels(close: float, atr: float, side: str, cfg: BacktestConfig):
    if side == "LONG":
        sl = close - cfg.atr_mult * atr
        return sl, close + cfg.min_rrr * (close - sl)
    sl = close + cfg.atr_mult * atr
    return sl, close - cfg.min_rrr * (sl - close)


def simulate(df_ltf: pd.DataFrame, df_htf: pd.DataFrame,
             bt: Optional[BacktestConfig] = None,
             conf: Optional[ConfluenceConfig] = None) -> List[Trade]:
    """Scan LTF bars; open trades on confluence signals; return closed trades."""
    bt = bt or BacktestConfig()
    conf = conf or ConfluenceConfig.from_settings()
    if len(df_ltf) <= bt.warmup + 1:
        return []

    trades: List[Trade] = []
    opens, highs, lows, closes = (df_ltf[k].to_numpy(float) for k in
                                  ("open", "high", "low", "close"))
    times = df_ltf.index
    n = len(df_ltf)
    # Precomputed once: boolean masks over the whole HTF frame per bar make
    # this loop O(n*m) and unusable beyond ~5k bars (20k x 80k never
    # finished). searchsorted gives the same "strictly before ts" boundary.
    htf_i8 = df_htf.index.asi8
    htf_pos = np.searchsorted(htf_i8, times.asi8, side="left")

    i = bt.warmup
    while i < n - 1:
        ltf_win = df_ltf.iloc[max(0, i - bt.window + 1): i + 1]
        pos = int(htf_pos[i])
        htf_win = df_htf.iloc[max(0, pos - bt.window):pos]
        report = _decide(ltf_win, htf_win, conf)
        if report.direction not in ("LONG", "SHORT") or report.score < bt.min_score \
                or report.atr is None:
            i += 1
            continue

        side = report.direction
        atr = report.atr
        signal_close = closes[i]
        sl, tp = _levels(signal_close, atr, side, bt)
        direction = 1.0 if side == "LONG" else -1.0
        fill_entry = opens[i + 1] * (1.0 + direction * bt.slippage_pct / 100.0)

        exit_j, exit_raw, reason = None, None, None
        last_j = min(i + bt.max_hold_bars, n - 1)
        for j in range(i + 1, last_j + 1):
            stop_hit = lows[j] <= sl if side == "LONG" else highs[j] >= sl
            tp_hit = highs[j] >= tp if side == "LONG" else lows[j] <= tp
            if stop_hit:                      # worst case when both in one bar
                exit_j, exit_raw, reason = j, sl, "STOP_LOSS"
                break
            if tp_hit:
                exit_j, exit_raw, reason = j, tp, "TAKE_PROFIT"
                break
        if exit_j is None:
            exit_j, exit_raw, reason = last_j, closes[last_j], "TIME_STOP"

        fill_exit = exit_raw * (1.0 - direction * bt.slippage_pct / 100.0)
        fee_in = fill_entry * bt.fee_pct / 100.0
        fee_out = abs(fill_exit) * bt.fee_pct / 100.0
        gross = (fill_exit - fill_entry) * direction
        pnl_pct = (gross - fee_in - fee_out) / fill_entry
        risk = abs(signal_close - sl)
        r_multiple = direction * (exit_raw - opens[i + 1]) / risk if risk > 0 else 0.0

        trades.append(Trade(
            entry_time=times[i + 1], exit_time=times[exit_j], side=side,
            entry=float(opens[i + 1]), fill_entry=float(fill_entry),
            exit_raw=float(exit_raw), fill_exit=float(fill_exit),
            sl=float(sl), tp=float(tp), score=report.score,
            exit_reason=reason, pnl_pct=float(pnl_pct), r_multiple=float(r_multiple),
        ))
        i = exit_j + 1     # one position at a time

    return trades


# ─── fold analysis ───────────────────────────────────────────────────────────

def _stats(trades: List[Trade]) -> Dict:
    if not trades:
        return {"trades": 0, "hit_rate": None, "avg_r": None, "avg_pnl_pct": None,
                "profit_factor": None}
    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs <= 0]
    pf = (wins.sum() / abs(losses.sum())) if losses.sum() != 0 else float("inf")
    return {
        "trades": len(trades),
        "hit_rate": round(float((rs > 0).mean()) * 100, 1),
        "avg_r": round(float(rs.mean()), 3),
        "avg_pnl_pct": round(float(np.mean([t.pnl_pct for t in trades])) * 100, 3),
        "profit_factor": round(float(pf), 2) if np.isfinite(pf) else "inf",
    }


@dataclass
class WalkForwardReport:
    period: str
    bars: int
    folds: List[Dict]
    thresholds: List[Dict]
    overall: Dict

    @staticmethod
    def _fmt(value, width: int, digits: int) -> str:
        if isinstance(value, (int, float)):
            return f"{value:>{width}.{digits}f}"
        return f"{'-':>{width}}"

    def to_text(self) -> str:
        fmt = self._fmt
        lines = [f"Walk-forward report | bars={self.bars} | period={self.period}",
                 "", "Folds (chronological):",
                 f"{'fold':>4} {'window':>46} {'n':>4} {'hit%':>6} {'avgR':>7} {'avgP&L%':>8} {'PF':>6}"]
        for f in self.folds:
            s = f["stats"]
            lines.append(f"{f['fold']:>4} {f['window']:>46} {s['trades']:>4} "
                         + fmt(s['hit_rate'], 6, 1) + " " + fmt(s['avg_r'], 7, 3)
                         + " " + fmt(s['avg_pnl_pct'], 8, 3) + " " + str(s['profit_factor']).rjust(6))
        lines += ["", "Score-threshold sweep (all folds pooled):",
                  f"{'min_score':>9} {'n':>4} {'hit%':>6} {'avgR':>7} {'avgP&L%':>8} {'PF':>6}"]
        for t in self.thresholds:
            s = t["stats"]
            lines.append(f"{t['threshold']:>9} {s['trades']:>4} " + fmt(s['hit_rate'], 6, 1)
                         + " " + fmt(s['avg_r'], 7, 3) + " " + fmt(s['avg_pnl_pct'], 8, 3)
                         + " " + str(s['profit_factor']).rjust(6))
        o = self.overall
        lines += ["", f"Overall: trades={o['trades']} hit={o['hit_rate']}% "
                      f"avgR={o['avg_r']} avgP&L={o['avg_pnl_pct']}% PF={o['profit_factor']}"]
        return "\n".join(lines)


def walk_forward(df_ltf: pd.DataFrame, df_htf: pd.DataFrame,
                 bt: Optional[BacktestConfig] = None,
                 conf: Optional[ConfluenceConfig] = None) -> WalkForwardReport:
    bt = bt or BacktestConfig()
    trades = simulate(df_ltf, df_htf, bt, conf)
    n = len(df_ltf)
    period = (f"{df_ltf.index[0]} .. {df_ltf.index[-1]}" if n else "empty")

    fold_bounds = np.array_split(np.arange(bt.warmup, max(bt.warmup, n)), max(1, bt.folds))
    folds = []
    for k, bounds in enumerate(fold_bounds, start=1):
        lo = df_ltf.index[bounds[0]] if len(bounds) else None
        hi = df_ltf.index[bounds[-1]] if len(bounds) else None
        fold_trades = [t for t in trades if lo is not None and lo <= t.entry_time <= hi]
        folds.append({"fold": k,
                      "window": f"{lo} .. {hi}" if lo is not None else "-",
                      "stats": _stats(fold_trades)})

    thresholds = [{"threshold": thr,
                   "stats": _stats([t for t in trades if t.score >= thr])}
                  for thr in bt.threshold_sweep]

    return WalkForwardReport(period=str(period), bars=n, folds=folds,
                             thresholds=thresholds, overall=_stats(trades))


