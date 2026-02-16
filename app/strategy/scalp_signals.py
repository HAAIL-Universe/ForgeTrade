"""Scalp entry signal evaluation — pullback + confirmation on M1/S5.

Only produces an entry when the higher-timeframe trend direction matches
the M1 candlestick pattern.
"""

from dataclasses import dataclass
from typing import Optional

from app.strategy.indicators import calculate_ema
from app.strategy.models import CandleData
from app.strategy.trend import TrendState


@dataclass(frozen=True)
class ScalpEntrySignal:
    """Describes a confirmed scalp entry."""

    direction: str        # "buy" or "sell"
    entry_price: float
    reason: str


def _is_bullish_engulfing(prev: CandleData, curr: CandleData) -> bool:
    """Return True if *curr* is a bullish engulfing relative to *prev*."""
    return (
        prev.close < prev.open  # previous was bearish
        and curr.close > curr.open  # current is bullish
        and curr.close > prev.open  # body engulfs prev body
        and curr.open <= prev.close
    )


def _is_bearish_engulfing(prev: CandleData, curr: CandleData) -> bool:
    """Return True if *curr* is a bearish engulfing relative to *prev*."""
    return (
        prev.close > prev.open  # previous was bullish
        and curr.close < curr.open  # current is bearish
        and curr.close < prev.open  # body engulfs prev body
        and curr.open >= prev.close
    )


def _is_hammer(candle: CandleData) -> bool:
    """Return True if *candle* is a hammer (bullish reversal)."""
    body = abs(candle.close - candle.open)
    lower_wick = min(candle.open, candle.close) - candle.low
    upper_wick = candle.high - max(candle.open, candle.close)
    if body == 0:
        return False
    return lower_wick >= 2 * body and upper_wick <= body * 0.5


def _is_shooting_star(candle: CandleData) -> bool:
    """Return True if *candle* is a shooting star (bearish reversal)."""
    body = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.open, candle.close)
    lower_wick = min(candle.open, candle.close) - candle.low
    if body == 0:
        return False
    return upper_wick >= 2 * body and lower_wick <= body * 0.5


def _has_momentum_buy(candles: list[CandleData]) -> tuple[bool, str]:
    """Two consecutive bullish candles (momentum continuation)."""
    if len(candles) < 2:
        return False, ""
    prev, curr = candles[-2], candles[-1]
    if prev.close > prev.open and curr.close > curr.open:
        return True, "bullish momentum"
    return False, ""


def _has_momentum_sell(candles: list[CandleData]) -> tuple[bool, str]:
    """Two consecutive bearish candles (momentum continuation)."""
    if len(candles) < 2:
        return False, ""
    prev, curr = candles[-2], candles[-1]
    if prev.close < prev.open and curr.close < curr.open:
        return True, "bearish momentum"
    return False, ""


def _is_bullish_pin_bar(candle: CandleData) -> bool:
    """A candle with a long lower wick showing buyer rejection."""
    body = abs(candle.close - candle.open)
    lower_wick = min(candle.open, candle.close) - candle.low
    total_range = candle.high - candle.low
    if total_range == 0:
        return False
    return lower_wick >= 0.6 * total_range and candle.close >= candle.open


def _is_bearish_pin_bar(candle: CandleData) -> bool:
    """A candle with a long upper wick showing seller rejection."""
    body = abs(candle.close - candle.open)
    upper_wick = candle.high - max(candle.open, candle.close)
    total_range = candle.high - candle.low
    if total_range == 0:
        return False
    return upper_wick >= 0.6 * total_range and candle.close <= candle.open


def _has_buy_confirmation(candles: list[CandleData]) -> tuple[bool, str]:
    """Check last 2 candles for a bullish reversal pattern."""
    if len(candles) < 2:
        return False, ""
    prev, curr = candles[-2], candles[-1]
    if _is_bullish_engulfing(prev, curr):
        return True, "bullish engulfing"
    if _is_hammer(curr):
        return True, "hammer"
    if _is_bullish_pin_bar(curr):
        return True, "bullish pin bar"
    confirmed, pattern = _has_momentum_buy(candles)
    if confirmed:
        return True, pattern
    return False, ""


def _has_sell_confirmation(candles: list[CandleData]) -> tuple[bool, str]:
    """Check last 2 candles for a bearish reversal pattern."""
    if len(candles) < 2:
        return False, ""
    prev, curr = candles[-2], candles[-1]
    if _is_bearish_engulfing(prev, curr):
        return True, "bearish engulfing"
    if _is_shooting_star(curr):
        return True, "shooting star"
    if _is_bearish_pin_bar(curr):
        return True, "bearish pin bar"
    confirmed, pattern = _has_momentum_sell(candles)
    if confirmed:
        return True, pattern
    return False, ""


def evaluate_scalp_entry(
    candles_m1: list[CandleData],
    candles_s5: list[CandleData],
    trend: TrendState,
    pullback_ema_period: int = 9,
) -> Optional[ScalpEntrySignal]:
    """Evaluate whether conditions are met for a scalp entry.

    Rules:
        1. Trend direction must not be flat.
        2. Price must have pulled back to EMA(9) on M1.
        3. A bullish/bearish confirmation candle on M1 or S5.
        4. Only enters WITH the trend (no counter-trend trades).

    Args:
        candles_m1: M1 candle history, oldest-first.  Need ≥ pullback_ema_period + 2.
        candles_s5: S5 candle history, oldest-first.
        trend: The higher-timeframe TrendState.
        pullback_ema_period: EMA period for pullback detection on M1.

    Returns:
        ``ScalpEntrySignal`` if conditions are met, else ``None``.
    """
    if trend.direction == "flat":
        return None

    if len(candles_m1) < pullback_ema_period + 2:
        return None

    # Calculate M1 EMA for pullback detection
    ema_values = calculate_ema(candles_m1, pullback_ema_period)
    if not ema_values:
        return None

    ema_current = ema_values[-1]
    last_close = candles_m1[-1].close

    if trend.direction == "bullish":
        # Price should be near or at/below the EMA (pullback)
        # "Near" = within 0.4% of EMA
        pullback_threshold = ema_current * 1.004
        if last_close > pullback_threshold:
            return None  # Price hasn't pulled back to EMA

        # Check for bullish confirmation
        confirmed, pattern = _has_buy_confirmation(candles_m1)
        if not confirmed and len(candles_s5) >= 2:
            confirmed, pattern = _has_buy_confirmation(candles_s5)
            if confirmed:
                pattern += " (S5)"

        if not confirmed:
            return None

        return ScalpEntrySignal(
            direction="buy",
            entry_price=candles_m1[-1].close,
            reason=f"Trend-scalp buy: {pattern} at M1 EMA({pullback_ema_period}) pullback",
        )

    elif trend.direction == "bearish":
        # Price should be near or at/above the EMA (pullback up)
        pullback_threshold = ema_current * 0.996
        if last_close < pullback_threshold:
            return None  # Price hasn't pulled back up to EMA

        # Check for bearish confirmation
        confirmed, pattern = _has_sell_confirmation(candles_m1)
        if not confirmed and len(candles_s5) >= 2:
            confirmed, pattern = _has_sell_confirmation(candles_s5)
            if confirmed:
                pattern += " (S5)"

        if not confirmed:
            return None

        return ScalpEntrySignal(
            direction="sell",
            entry_price=candles_m1[-1].close,
            reason=f"Trend-scalp sell: {pattern} at M1 EMA({pullback_ema_period}) pullback",
        )

    return None
