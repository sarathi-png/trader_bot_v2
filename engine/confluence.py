"""
Multi-timeframe confluence scoring (Stage 2: signal quality).

Scores a candidate setup 0-100 from four weighted components, each signed
in [-1, +1] where positive is bullish:

  trend     HTF EMA(fast,slow) separation scaled by ATR, blended with the
            swing-structure trend from engine.trendlines.
  zone      LTF wick-rejection at the nearest S/R zone (support rejection
            scores bullish, resistance rejection bearish, failed support
            scores negative).
  momentum  LTF RSI displacement from 50 blended with EMA-slope strength.
  volume    Last-bar volume expansion vs its 20-bar mean, signed by the
            momentum direction (volume confirms, it never leads).

net = sum(w_i * c_i) / sum(w_i) in [-1, +1]
score = 50 * (1 + net); direction = LONG/SHORT above the configured
threshold, else NEUTRAL.

Look-ahead safety: every component reads only from the tail of the frames
passed in. Callers must pass CLOSED candles up to the decision bar
(fetch_recent_candles(confirm_only=True) live; explicit window slices in
backtest/walk_forward.py).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from engine.indicators import atr_14, rsi
from engine.sr_zones import cluster_zones, find_nearest_zones, find_swing_high_low
from engine.trendlines import get_trend_direction

_MIN_BARS = 40


@dataclass(frozen=True)
class ConfluenceConfig:
    weight_trend: float = 0.35
    weight_zone: float = 0.25
    weight_momentum: float = 0.25
    weight_volume: float = 0.15
    htf_ema_fast: int = 20
    htf_ema_slow: int = 50
    mom_ema: int = 9
    rsi_period: int = 14
    swing_n: int = 5
    zone_tolerance_pct: float = 0.003
    zone_atr_mult: float = 0.6      # max |close-zone| / ATR to count as "at" a zone
    wick_min_ratio: float = 0.45    # wick/range ratio that qualifies as a rejection
    direction_threshold: float = 0.15
    min_score: float = 55.0
    veto_opposite: bool = True
    enabled: bool = True

    @classmethod
    def from_settings(cls) -> "ConfluenceConfig":
        from config import settings as s
        return cls(
            weight_trend=getattr(s, "CONFLUENCE_W_TREND", cls.weight_trend),
            weight_zone=getattr(s, "CONFLUENCE_W_ZONE", cls.weight_zone),
            weight_momentum=getattr(s, "CONFLUENCE_W_MOMENTUM", cls.weight_momentum),
            weight_volume=getattr(s, "CONFLUENCE_W_VOLUME", cls.weight_volume),
            htf_ema_fast=getattr(s, "CONFLUENCE_EMA_FAST", cls.htf_ema_fast),
            htf_ema_slow=getattr(s, "CONFLUENCE_EMA_SLOW", cls.htf_ema_slow),
            swing_n=getattr(s, "N_SWING", cls.swing_n),
            zone_tolerance_pct=getattr(s, "ZONE_TOLERANCE_PCT", cls.zone_tolerance_pct),
            direction_threshold=getattr(s, "CONFLUENCE_DIRECTION_THRESHOLD",
                                        cls.direction_threshold),
            min_score=getattr(s, "CONFLUENCE_MIN_SCORE", cls.min_score),
            veto_opposite=getattr(s, "CONFLUENCE_VETO_OPPOSITE", cls.veto_opposite),
            enabled=getattr(s, "CONFLUENCE_ENABLED", cls.enabled),
        )


@dataclass
class ConfluenceReport:
    score: float = 50.0
    direction: str = "NEUTRAL"          # LONG | SHORT | NEUTRAL
    components: Dict[str, float] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)
    atr: Optional[float] = None         # LTF ATR at the decision bar
    htf_support: Optional[float] = None
    htf_resistance: Optional[float] = None

    def to_signal_fields(self) -> Dict[str, Any]:
        return {
            "confluence_score": self.score,
            "confluence_direction": self.direction,
            "confluence_components": {k: round(v, 3) for k, v in self.components.items()},
            "confluence_reasons": self.reasons,
        }


def _neutral(reason: str) -> ConfluenceReport:
    return ConfluenceReport(components={k: 0.0 for k in
                                        ("trend", "zone", "momentum", "volume")},
                            reasons=[reason])


def _clip(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


# ─── components ──────────────────────────────────────────────────────────────

def trend_component(df_htf: pd.DataFrame, cfg: ConfluenceConfig) -> Tuple[float, str, Optional[float]]:
    close = df_htf["close"]
    fast = close.ewm(span=cfg.htf_ema_fast, adjust=False).mean()
    slow = close.ewm(span=cfg.htf_ema_slow, adjust=False).mean()
    atr = atr_14(df_htf)
    atr_last = float(atr.iloc[-1]) if not np.isnan(atr.iloc[-1]) else None
    if atr_last is None or atr_last <= 0:
        return 0.0, "trend=0.00 (htf ATR unavailable)", None
    sep = float(fast.iloc[-1] - slow.iloc[-1])
    amp = _clip(abs(sep) / (0.5 * atr_last), 0.0, 1.0)
    ema_comp = np.sign(sep) * amp
    swings = find_swing_high_low(df_htf, n=cfg.swing_n)
    swing_trend = get_trend_direction(swings, n_swings=cfg.swing_n)
    swing_sign = {"uptrend": 1.0, "downtrend": -1.0}.get(swing_trend, 0.0)
    comp = _clip(0.7 * float(ema_comp) + 0.3 * swing_sign)
    reason = (f"trend={comp:+.2f} (ema_gap={sep / atr_last:+.2f}atr "
              f"{cfg.htf_ema_fast}g{cfg.htf_ema_slow}, structure={swing_trend})")
    return comp, reason, atr_last


def zone_component(df_ltf: pd.DataFrame, cfg: ConfluenceConfig,
                   atr_last: float) -> Tuple[float, str]:
    swings = find_swing_high_low(df_ltf, n=cfg.swing_n)
    sup_zones = cluster_zones(swings["swing_low"], swings["low"],
                              tolerance_pct=cfg.zone_tolerance_pct)
    res_zones = cluster_zones(swings["swing_high"], swings["high"],
                              tolerance_pct=cfg.zone_tolerance_pct)
    close_last = float(df_ltf["close"].iloc[-1])

    # Nearest zone EDGE to price, on either side — so a just-broken zone
    # (price now beyond it) is still the relevant level to judge.
    support = min((float(zh) for _, zh in sup_zones),
                  key=lambda z: abs(close_last - z), default=None)
    resistance = min((float(zl) for zl, _ in res_zones),
                     key=lambda z: abs(close_last - z), default=None)

    long_score, long_note = 0.0, ""
    if support is not None:
        if close_last < support - 0.2 * atr_last:
            long_score = -0.6
            long_note = f"support {support:.8g} broken (-0.60)"
        elif abs(close_last - support) <= cfg.zone_atr_mult * atr_last:  # at support
            best = 0.0
            for age, decay in enumerate((1.0, 0.7, 0.5)):  # last 3 closed bars
                if len(df_ltf) < age + 1:
                    break
                bar = df_ltf.iloc[-(age + 1)]
                rng = float(bar["high"] - bar["low"])
                if rng <= 0:
                    continue
                body_low = min(float(bar["open"]), float(bar["close"]))
                lower_ratio = (body_low - float(bar["low"])) / rng
                touched = float(bar["low"]) <= support + 0.15 * atr_last
                reclaimed = float(bar["close"]) > support
                if touched and reclaimed and lower_ratio >= cfg.wick_min_ratio:
                    best = max(best, _clip(lower_ratio, 0.0, 1.0) * decay)
            if best > 0:
                long_score = best
                long_note = f"bullish wick rejection at support {support:.8g}"

    short_score, short_note = 0.0, ""
    if resistance is not None:
        if close_last > resistance + 0.2 * atr_last:
            short_score = -0.6  # failed resistance is bullish
            short_note = f"resistance {resistance:.8g} broken (bullish -0.60)"
        elif abs(close_last - resistance) <= cfg.zone_atr_mult * atr_last:  # at resistance
            best = 0.0
            for age, decay in enumerate((1.0, 0.7, 0.5)):
                if len(df_ltf) < age + 1:
                    break
                bar = df_ltf.iloc[-(age + 1)]
                rng = float(bar["high"] - bar["low"])
                if rng <= 0:
                    continue
                body_high = max(float(bar["open"]), float(bar["close"]))
                upper_ratio = (float(bar["high"]) - body_high) / rng
                touched = float(bar["high"]) >= resistance - 0.15 * atr_last
                reclaimed = float(bar["close"]) < resistance
                if touched and reclaimed and upper_ratio >= cfg.wick_min_ratio:
                    best = max(best, _clip(upper_ratio, 0.0, 1.0) * decay)
            if best > 0:
                short_score = best
                short_note = f"bearish wick rejection at resistance {resistance:.8g}"

    comp = _clip(long_score - short_score)
    note = long_note or short_note or "no qualifying zone interaction"
    return comp, f"zone={comp:+.2f} ({note})"


def momentum_component(df_ltf: pd.DataFrame, cfg: ConfluenceConfig,
                       atr_last: float) -> Tuple[float, str]:
    rsi_series = rsi(df_ltf, period=cfg.rsi_period)
    rsi_last = float(rsi_series.iloc[-1])
    if np.isnan(rsi_last):
        return 0.0, "momentum=+0.00 (rsi unavailable)"
    rsi_comp = _clip((rsi_last - 50.0) / 20.0)
    ema = df_ltf["close"].ewm(span=cfg.mom_ema, adjust=False).mean()
    slope = float(ema.iloc[-1] - ema.iloc[-4]) / atr_last if len(ema) >= 4 else 0.0
    slope_comp = _clip(slope)
    comp = _clip(0.6 * rsi_comp + 0.4 * slope_comp)
    return comp, (f"momentum={comp:+.2f} (rsi={rsi_last:.1f}, "
                  f"ema{cfg.mom_ema} slope={slope:+.2f}atr/3bars)")


def volume_component(df_ltf: pd.DataFrame, momentum: float) -> Tuple[float, str]:
    if "volume" not in df_ltf.columns or len(df_ltf) < 21:
        return 0.0, "volume=+0.00 (unavailable)"
    volumes = pd.to_numeric(df_ltf["volume"], errors="coerce").fillna(0.0)
    baseline = float(volumes.iloc[-21:-1].mean())
    last = float(volumes.iloc[-1])
    if baseline <= 0:
        return 0.0, "volume=+0.00 (zero baseline)"
    ratio = last / baseline
    comp = _clip(max(0.0, ratio - 1.0), 0.0, 1.0) * float(np.sign(momentum))
    return comp, f"volume={comp:+.2f} (last bar {ratio:.2f}x 20-bar avg)"


# ─── aggregation ─────────────────────────────────────────────────────────────

def analyze_confluence(df_ltf: pd.DataFrame, df_htf: pd.DataFrame,
                       cfg: Optional[ConfluenceConfig] = None) -> ConfluenceReport:
    cfg = cfg or ConfluenceConfig.from_settings()
    if df_ltf is None or df_htf is None or len(df_ltf) < _MIN_BARS or len(df_htf) < _MIN_BARS:
        return _neutral(f"insufficient data (ltf={0 if df_ltf is None else len(df_ltf)}, "
                        f"htf={0 if df_htf is None else len(df_htf)}, need {_MIN_BARS})")

    trend, r_trend, _htf_atr = trend_component(df_htf, cfg)
    ltf_atr_series = atr_14(df_ltf)
    if np.isnan(ltf_atr_series.iloc[-1]) or ltf_atr_series.iloc[-1] <= 0:
        return _neutral("ltf ATR unavailable")
    atr_last = float(ltf_atr_series.iloc[-1])

    zone, r_zone = zone_component(df_ltf, cfg, atr_last)
    mom, r_mom = momentum_component(df_ltf, cfg, atr_last)
    vol, r_vol = volume_component(df_ltf, mom)

    weights = [cfg.weight_trend, cfg.weight_zone,
               cfg.weight_momentum, cfg.weight_volume]
    comps = [trend, zone, mom, vol]
    total_w = sum(weights)
    net = sum(w * c for w, c in zip(weights, comps)) / total_w if total_w else 0.0

    score = round(50.0 * (1.0 + net), 1)
    direction = ("LONG" if net >= cfg.direction_threshold
                 else "SHORT" if net <= -cfg.direction_threshold else "NEUTRAL")

    zoned = find_nearest_zones(df_htf, n=cfg.swing_n,
                               tolerance_pct=cfg.zone_tolerance_pct)
    htf_support = zoned["nearest_support"].iloc[-1]
    htf_resistance = zoned["nearest_resistance"].iloc[-1]

    return ConfluenceReport(
        score=score,
        direction=direction,
        components={"trend": trend, "zone": zone, "momentum": mom, "volume": vol},
        reasons=[r_trend, r_zone, r_mom, r_vol],
        atr=atr_last,
        htf_support=None if pd.isna(htf_support) else float(htf_support),
        htf_resistance=None if pd.isna(htf_resistance) else float(htf_resistance),
    )


def gate_signal(report: ConfluenceReport, side: str,
                cfg: Optional[ConfluenceConfig] = None) -> Tuple[bool, str]:
    """Decide whether a candidate signal passes the confluence gate.

    side: 'long'/BUY or 'short'/SELL. Returns (passed, reason).
    A setup's quality is measured relative to ITS side: a SHORT setup at
    score 30 is as strong as a LONG setup at 70.
    """
    cfg = cfg or ConfluenceConfig.from_settings()
    if not cfg.enabled:
        return True, "confluence disabled"
    wanted = "LONG" if str(side).upper() in ("LONG", "BUY", "B") else "SHORT"
    if cfg.veto_opposite and report.direction not in ("NEUTRAL", wanted):
        return False, (f"CONFLUENCE_VETO: score {report.score:.0f} points "
                       f"{report.direction}, signal is {wanted}")
    side_score = report.score if wanted == "LONG" else 100.0 - report.score
    if side_score < cfg.min_score:
        return False, (f"LOW_CONFLUENCE: side score {side_score:.0f} "
                       f"< minimum {cfg.min_score:.0f}")
    return True, f"confluence ok ({side_score:.0f} >= {cfg.min_score:.0f})"


    comp = _clip(long_score - short_score)
    note = long_note or short_note or "no qualifying zone interaction"
    return comp, f"zone={comp:+.2f} ({note})"

