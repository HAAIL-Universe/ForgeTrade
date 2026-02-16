"""Trend detection — EMA-based directional bias on H1 candles.

Determines whether the market is bullish, bearish, or flat by comparing
fast and slow EMA values against the most recent close.
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
