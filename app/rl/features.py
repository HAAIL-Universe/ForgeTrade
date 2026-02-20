"""Feature engineering — 27-feature state vector for ForgeAgent.

Builds the normalised observation vector the RL agent sees at each
decision point.  All features are scale-invariant (no raw prices).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from typing import Optional

import numpy as np

from app.strategy.indicators import (
    calculate_atr,
    calculate_bollinger,
    calculate_ema,
    calculate_rsi,
)
from app.strategy.models import CandleData
from app.strategy.trend import detect_scalp_bias, detect_trend, TrendState


# ── Utility helpers ──────────────────────────────────────────────────────


def percentile_rank(values: list[float], current: float) -> float:
    """Return the percentile rank of *current* within *values* ∈ [0, 1]."""
    if not values:
        return 0.5
    below = sum(1 for v in values if v < current)
    return below / len(values)


def cyclical_encode(value: float, max_value: float) -> tuple[float, float]:
    """Sine/cosine encoding for cyclical features (e.g. hour-of-day)."""
    angle = 2 * math.pi * value / max_value
    return math.sin(angle), math.cos(angle)


def clip_feature(value: float, low: float, high: float) -> float:
    """Clip a feature to [low, high]."""
    return max(low, min(high, value))


def distance_to_round_level(price: float, multiple: float) -> float:
    """Distance from *price* to the nearest round *multiple* level."""
    nearest = round(price / multiple) * multiple
    return abs(price - nearest)


def safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Safe division — returns *default* when divisor is zero/near-zero."""
    if abs(b) < 1e-12:
        return default
    return a / b


# ── 27-feature state vector ─────────────────────────────────────────────


STATE_DIM = 27


@dataclass
class ForgeState:
    """The 27 features the RL agent observes at each decision point."""

    # Group 1 — Trend / Momentum (6)
    m5_ema9_distance: float = 0.0
    m5_ema_slope: float = 0.0
    m5_bias_direction: float = 0.0
    m5_consecutive_candles: float = 0.0
    h1_trend_agreement: float = 0.0
    h1_ema_slope: float = 0.0

    # Group 2 — Volatility (4)
    m5_atr_percentile: float = 0.0
    m5_bb_width: float = 0.0
    m5_bb_position: float = 0.0
    vol_expansion_rate: float = 0.0

    # Group 3 — RSI / Oscillator (2)
    m15_rsi_norm: float = 0.0
    m5_rsi_norm: float = 0.0

    # Group 4 — Candle Structure (4)
    m5_body_ratio: float = 0.0
    m5_upper_wick_ratio: float = 0.0
    m5_lower_wick_ratio: float = 0.0
    m1_avg_body_ratio: float = 0.0

    # Group 5 — Session / Time (4)
    hour_sin: float = 0.0
    hour_cos: float = 0.0
    day_of_week: float = 0.0
    minutes_in_session: float = 0.0

    # Group 6 — Spread / Cost (2)
    spread_to_atr: float = 0.0
    spread_pips_norm: float = 0.0

    # Group 7 — Price Structure (3)
    dist_to_round_50: float = 0.0
    dist_to_round_100: float = 0.0
    dist_to_nearest_sr: float = 0.0

    # Group 8 — Account / Performance (2)
    current_drawdown: float = 0.0
    recent_trade_performance: float = 0.0

    def to_array(self) -> np.ndarray:
        """Convert to float32 numpy array of shape (27,)."""
        values = [getattr(self, f.name) for f in fields(self)]
        arr = np.array(values, dtype=np.float32)
        # Safety: replace NaN/Inf with 0
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        return arr


# ── Account state for feature computation ────────────────────────────────


@dataclass
class AccountSnapshot:
    """Minimal account state needed for feature computation."""

    drawdown_pct: float = 0.0           # Current DD / max_allowed
    max_drawdown_pct: float = 10.0      # Config max DD
    recent_r_multiples: list[float] = None  # Last 5 trade R-multiples

    def __post_init__(self):
        if self.recent_r_multiples is None:
            self.recent_r_multiples = []


# ── State builder ────────────────────────────────────────────────────────


class ForgeStateBuilder:
    """Builds a ForgeState from raw candle data + account state.

    Reuses existing indicator functions from ``app.strategy.indicators``.
    """

    MAX_SPREAD_PIPS: float = 8.0  # from TrendScalpStrategy

    def build(
        self,
        m5_candles: list[CandleData],
        m1_candles: list[CandleData],
        h1_candles: list[CandleData],
        m15_candles: list[CandleData],
        account: Optional[AccountSnapshot] = None,
        current_spread_pips: float = 0.0,
        pip_value: float = 0.01,
    ) -> ForgeState:
        """Build the 27-feature state vector.

        All candles should be oldest-first.

        Args:
            m5_candles: ≥ 100 M5 candles ideally.
            m1_candles: ≥ 20 M1 candles.
            h1_candles: ≥ 50 H1 candles.
            m15_candles: ≥ 30 M15 candles.
            account: Current account snapshot.
            current_spread_pips: Current bid-ask spread in pips.
            pip_value: Pip multiplier for the instrument.
        """
        if account is None:
            account = AccountSnapshot()

        state = ForgeState()

        # ── Safe indicator computation ──────────────────────────────
        m5_atr = self._safe_atr(m5_candles, 14)
        h1_atr = self._safe_atr(h1_candles, 14)

        m5_ema9 = self._safe_ema(m5_candles, 9)
        h1_ema21 = self._safe_ema(h1_candles, 21)
        h1_ema50 = self._safe_ema(h1_candles, 50)

        m5_rsi = self._safe_rsi(m5_candles, 14)
        m15_rsi = self._safe_rsi(m15_candles, 14)

        bb_upper, bb_mid, bb_lower = self._safe_bollinger(m5_candles, 20, 2.0)

        price = m5_candles[-1].close if m5_candles else 0.0

        # ── Group 1: Trend / Momentum ───────────────────────────────
        if m5_ema9 is not None and m5_atr > 0:
            state.m5_ema9_distance = clip_feature(
                safe_div(price - m5_ema9, m5_atr), -3.0, 3.0
            )

        if m5_ema9 is not None and len(m5_candles) >= 15:
            ema_vals = calculate_ema(m5_candles, 9)
            if len(ema_vals) >= 6 and not math.isnan(ema_vals[-6]):
                slope = ema_vals[-1] - ema_vals[-6]
                state.m5_ema_slope = clip_feature(
                    safe_div(slope, m5_atr) if m5_atr > 0 else 0.0, -2.0, 2.0
                )

        # Bias direction
        if len(m5_candles) >= 15:
            bias = detect_scalp_bias(m5_candles, lookback=15, pip_value=pip_value)
            state.m5_bias_direction = {"bullish": 1.0, "bearish": -1.0}.get(
                bias.direction, 0.0
            )

            # Consecutive candles
            direction = bias.direction
            count = 0
            for c in reversed(m5_candles):
                if direction == "bullish" and c.close > c.open:
                    count += 1
                elif direction == "bearish" and c.close < c.open:
                    count += 1
                else:
                    break
            state.m5_consecutive_candles = clip_feature(count / 10.0, 0.0, 1.0)
        else:
            bias = TrendState(direction="flat", ema_fast_value=0.0, ema_slow_value=0.0, slope=0.0)

        # H1 trend agreement
        if h1_ema21 is not None and h1_ema50 is not None:
            h1_bullish = h1_ema21 > h1_ema50
            if h1_bullish and bias.direction == "bullish":
                state.h1_trend_agreement = 1.0
            elif not h1_bullish and bias.direction == "bearish":
                state.h1_trend_agreement = -1.0
            else:
                state.h1_trend_agreement = 0.0

        # H1 EMA slope
        if len(h1_candles) >= 25:
            h1_ema_vals = calculate_ema(h1_candles, 21)
            if len(h1_ema_vals) >= 4 and not math.isnan(h1_ema_vals[-4]):
                h1_slope = h1_ema_vals[-1] - h1_ema_vals[-4]
                state.h1_ema_slope = clip_feature(
                    safe_div(h1_slope, h1_atr) if h1_atr > 0 else 0.0, -1.5, 1.5
                )

        # ── Group 2: Volatility ─────────────────────────────────────
        if len(m5_candles) >= 115:
            atr_history = []
            for i in range(100):
                end_idx = len(m5_candles) - i
                if end_idx >= 15:
                    try:
                        a = calculate_atr(m5_candles[:end_idx], 14)
                        atr_history.append(a)
                    except ValueError:
                        pass
            if atr_history:
                state.m5_atr_percentile = percentile_rank(atr_history, m5_atr)
        elif m5_atr > 0:
            state.m5_atr_percentile = 0.5  # Default to median

        if bb_upper is not None and bb_lower is not None and price > 0:
            bb_width = bb_upper - bb_lower
            state.m5_bb_width = clip_feature(safe_div(bb_width, price), 0.0, 0.05)
            state.m5_bb_position = clip_feature(
                safe_div(price - bb_lower, bb_width), -0.5, 1.5
            )

        if len(m5_candles) >= 25:
            try:
                atr_now = calculate_atr(m5_candles, 14)
                # ATR 10 bars ago
                if len(m5_candles) >= 25:
                    atr_10ago = calculate_atr(m5_candles[:-10], 14)
                    state.vol_expansion_rate = clip_feature(
                        safe_div(atr_now, atr_10ago), 0.5, 2.0
                    )
            except ValueError:
                pass

        # ── Group 3: RSI ────────────────────────────────────────────
        if m15_rsi is not None:
            state.m15_rsi_norm = clip_feature((m15_rsi - 50.0) / 50.0, -1.0, 1.0)
        if m5_rsi is not None:
            state.m5_rsi_norm = clip_feature((m5_rsi - 50.0) / 50.0, -1.0, 1.0)

        # ── Group 4: Candle Structure ───────────────────────────────
        if m5_candles:
            last_m5 = m5_candles[-1]
            rng = last_m5.high - last_m5.low
            if rng > 0:
                body = abs(last_m5.close - last_m5.open)
                state.m5_body_ratio = clip_feature(body / rng, 0.0, 1.0)
                state.m5_upper_wick_ratio = clip_feature(
                    (last_m5.high - max(last_m5.open, last_m5.close)) / rng, 0.0, 1.0
                )
                state.m5_lower_wick_ratio = clip_feature(
                    (min(last_m5.open, last_m5.close) - last_m5.low) / rng, 0.0, 1.0
                )

        if len(m1_candles) >= 3:
            ratios = []
            for c in m1_candles[-3:]:
                rng = c.high - c.low
                if rng > 0:
                    ratios.append(abs(c.close - c.open) / rng)
                else:
                    ratios.append(0.0)
            state.m1_avg_body_ratio = clip_feature(sum(ratios) / len(ratios), 0.0, 1.0)

        # ── Group 5: Session / Time ─────────────────────────────────
        if m5_candles and m5_candles[-1].time:
            try:
                from datetime import datetime as _dt
                ts = m5_candles[-1].time
                if isinstance(ts, str):
                    # Parse multiple ISO formats
                    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                                "%Y-%m-%dT%H:%M:%S.%f+00:00", "%Y-%m-%dT%H:%M:%S+00:00"):
                        try:
                            dt = _dt.strptime(ts, fmt)
                            break
                        except ValueError:
                            dt = None
                    if dt is None:
                        # Fallback with pandas
                        import pandas as _pd
                        dt = _pd.Timestamp(ts).to_pydatetime()
                else:
                    dt = ts  # already datetime

                hour = dt.hour + dt.minute / 60.0
                state.hour_sin, state.hour_cos = cyclical_encode(hour, 24.0)
                state.day_of_week = clip_feature(dt.weekday() / 4.0, 0.0, 1.0)

                # Minutes in session (assume 24h for XAU_USD)
                total_minutes = 24 * 60
                minutes_elapsed = dt.hour * 60 + dt.minute
                state.minutes_in_session = clip_feature(
                    minutes_elapsed / total_minutes, 0.0, 1.0
                )
            except Exception:
                pass

        # ── Group 6: Spread / Cost ──────────────────────────────────
        spread_absolute = current_spread_pips * pip_value
        if m5_atr > 0:
            state.spread_to_atr = clip_feature(
                safe_div(spread_absolute, m5_atr), 0.0, 0.20
            )
        state.spread_pips_norm = clip_feature(
            safe_div(current_spread_pips, self.MAX_SPREAD_PIPS), 0.0, 1.5
        )

        # ── Group 7: Price Structure ────────────────────────────────
        if price > 0 and m5_atr > 0:
            state.dist_to_round_50 = clip_feature(
                safe_div(distance_to_round_level(price, 50.0), m5_atr), 0.0, 5.0
            )
            state.dist_to_round_100 = clip_feature(
                safe_div(distance_to_round_level(price, 100.0), m5_atr), 0.0, 5.0
            )
            # S/R zone distance — default to far (no zone detected)
            state.dist_to_nearest_sr = 5.0

        # ── Group 8: Account / Performance ──────────────────────────
        if account.max_drawdown_pct > 0:
            state.current_drawdown = clip_feature(
                safe_div(account.drawdown_pct, account.max_drawdown_pct), 0.0, 1.5
            )

        if account.recent_r_multiples:
            avg_r = sum(account.recent_r_multiples[-5:]) / min(
                len(account.recent_r_multiples), 5
            )
            state.recent_trade_performance = clip_feature(avg_r / 2.0, -1.0, 1.0)

        return state

    # ── Safe indicator wrappers ──────────────────────────────────────

    @staticmethod
    def _safe_atr(candles: list[CandleData], period: int) -> float:
        try:
            return calculate_atr(candles, period)
        except (ValueError, IndexError):
            return 0.0

    @staticmethod
    def _safe_ema(candles: list[CandleData], period: int) -> Optional[float]:
        try:
            vals = calculate_ema(candles, period)
            v = vals[-1]
            return None if math.isnan(v) else v
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _safe_rsi(candles: list[CandleData], period: int) -> Optional[float]:
        try:
            vals = calculate_rsi(candles, period)
            # Find last non-NaN
            for v in reversed(vals):
                if not math.isnan(v):
                    return v
            return None
        except (ValueError, IndexError):
            return None

    @staticmethod
    def _safe_bollinger(
        candles: list[CandleData], period: int, std: float
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        try:
            upper, mid, lower = calculate_bollinger(candles, period, std)
            u = upper[-1] if not math.isnan(upper[-1]) else None
            m = mid[-1] if not math.isnan(mid[-1]) else None
            lo = lower[-1] if not math.isnan(lower[-1]) else None
            return u, m, lo
        except (ValueError, IndexError):
            return None, None, None
