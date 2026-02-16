"""Trend detection — EMA-based directional bias and momentum bias.

Provides two detection modes:
- ``detect_trend()``: Classical dual-EMA crossover for swing/multi-TF analysis.
- ``detect_scalp_bias()``: Fast momentum bias using M1 candle counting for
  scalp strategies. Returns bullish/bearish far more often than ``detect_trend``,
  only returning "flat" when the market is genuinely directionless.
"""

from dataclasses import dataclass
from typing import Literal

from app.strategy.indicators import calculate_ema
from app.strategy.models import CandleData


@dataclass(frozen=True)
class TrendState:
    """Snapshot of the current trend direction and EMA values."""

    direction: Literal["bullish", "bearish", "flat"]
    ema_fast_value: float
    ema_slow_value: float
    slope: float  # ema_fast - ema_slow (positive = bullish bias)


def detect_trend(
    candles_h1: list[CandleData],
    ema_fast: int = 21,
    ema_slow: int = 50,
) -> TrendState:
    """Classify trend direction using dual-EMA crossover and price position.

    Args:
        candles_h1: Candle history, oldest-first.
        ema_fast: Fast EMA period (default 21).
        ema_slow: Slow EMA period (default 50).

    Returns:
        ``TrendState`` with direction "bullish", "bearish", or "flat".

    Rules:
        - **Bullish**: EMA(fast) > EMA(slow) AND price > EMA(fast).
        - **Bearish**: EMA(fast) < EMA(slow) AND price < EMA(fast).
        - **Flat**: everything else (EMAs crossing, price between EMAs).
    """
    if len(candles_h1) < ema_slow:
        return TrendState(
            direction="flat",
            ema_fast_value=0.0,
            ema_slow_value=0.0,
            slope=0.0,
        )

    fast_values = calculate_ema(candles_h1, ema_fast)
    slow_values = calculate_ema(candles_h1, ema_slow)

    ema_f = fast_values[-1]
    ema_s = slow_values[-1]
    price = candles_h1[-1].close
    slope = ema_f - ema_s

    if ema_f > ema_s and price > ema_f:
        direction = "bullish"
    elif ema_f < ema_s and price < ema_f:
        direction = "bearish"
    else:
        direction = "flat"

    return TrendState(
        direction=direction,
        ema_fast_value=ema_f,
        ema_slow_value=ema_s,
        slope=slope,
    )


def detect_scalp_bias(
    candles_m1: list[CandleData],
    lookback: int = 15,
    bullish_threshold: float = 0.60,
    min_net_pips: float = 1.0,
    pip_value: float = 0.01,
) -> TrendState:
    """Determine short-term directional bias from recent M1 candles.

    Unlike ``detect_trend()`` which uses EMA crossover (slow, often flat),
    this counts bullish vs bearish candles over a short window and checks
    net price change.  It returns "flat" only when the market is genuinely
    directionless (~5-10% of the time).

    Args:
        candles_m1: M1 candle history, oldest-first.
        lookback: Number of recent candles to analyse (default 15 = 15 min).
        bullish_threshold: Fraction required to confirm bias (default 0.60).
        min_net_pips: Minimum net change in pips to break a tie (default 1.0).
        pip_value: Pip size for the instrument (default 0.01 for XAU_USD).

    Returns:
        ``TrendState`` with direction "bullish", "bearish", or "flat".
        ``ema_fast_value`` is set to the last close price.
        ``ema_slow_value`` is set to the first open of the window.
        ``slope`` is the net price change expressed in pips.
    """
    _flat = TrendState(direction="flat", ema_fast_value=0.0,
                       ema_slow_value=0.0, slope=0.0)

    if len(candles_m1) < lookback:
        return _flat

    window = candles_m1[-lookback:]

    # Count bullish / bearish (dojis are neutral)
    bullish_count = 0
    bearish_count = 0
    for c in window:
        if c.close > c.open:
            bullish_count += 1
        elif c.close < c.open:
            bearish_count += 1
        # doji (close == open) → neither

    total = bullish_count + bearish_count
    if total == 0:
        return _flat

    net_change = window[-1].close - window[0].open
    net_pips = net_change / pip_value if pip_value else 0.0

    bullish_frac = bullish_count / total
    bearish_frac = bearish_count / total

    # Primary: candle majority + net change agreement
    if bullish_frac >= bullish_threshold and net_change > 0:
        direction = "bullish"
    elif bearish_frac >= bullish_threshold and net_change < 0:
        direction = "bearish"
    # Conflict: candle majority says one thing, net change says opposite → flat
    elif bullish_frac >= bullish_threshold and net_change < 0:
        direction = "flat"
    elif bearish_frac >= bullish_threshold and net_change > 0:
        direction = "flat"
    # Tiebreaker: neither side reaches threshold — use net change if significant
    elif abs(net_pips) >= min_net_pips:
        direction = "bullish" if net_change > 0 else "bearish"
    else:
        direction = "flat"

    return TrendState(
        direction=direction,
        ema_fast_value=window[-1].close,
        ema_slow_value=window[0].open,
        slope=round(net_pips, 2),
    )
