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
    """Check last few candles for a bullish entry pattern."""
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
    # Single bullish candle with decent body (not a doji)
    body = curr.close - curr.open
    total = curr.high - curr.low
    if total > 0 and curr.close > curr.open and body / total >= 0.4:
        return True, "bullish candle"
    return False, ""


def _has_sell_confirmation(candles: list[CandleData]) -> tuple[bool, str]:
    """Check last few candles for a bearish entry pattern."""
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
    # Single bearish candle with decent body (not a doji)
    body = curr.open - curr.close
    total = curr.high - curr.low
    if total > 0 and curr.close < curr.open and body / total >= 0.4:
        return True, "bearish candle"
    return False, ""


def evaluate_scalp_entry(
    candles_m1: list[CandleData],
    candles_s5: list[CandleData],
    trend: TrendState,
    pullback_ema_period: int = 9,
) -> Optional[ScalpEntrySignal]:
    """Evaluate whether conditions are met for a scalp entry.

    Supports both with-trend and counter-trend entries:
        - **With trend**: price near EMA + any confirmation candle.
        - **Counter-trend**: requires a strong reversal pattern
          (engulfing, hammer/star, pin bar) — momentum alone is not enough.

    Args:
        candles_m1: M1 candle history, oldest-first.  Need >= pullback_ema_period + 2.
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

    # Calculate M1 EMA for proximity checks
    ema_values = calculate_ema(candles_m1, pullback_ema_period)
    if not ema_values:
        return None

    ema_current = ema_values[-1]
    last_close = candles_m1[-1].close

    # ── Helper: check confirmation on M1, fallback to S5
    def _check_confirm(check_fn):
        confirmed, pattern = check_fn(candles_m1)
        if not confirmed and len(candles_s5) >= 2:
            confirmed, pattern = check_fn(candles_s5)
            if confirmed:
                pattern += " (S5)"
        return confirmed, pattern

    # ── Helper: check for STRONG reversal only (no momentum/single candle)
    def _has_strong_buy(candles):
        if len(candles) < 2:
            return False, ""
        prev, curr = candles[-2], candles[-1]
        if _is_bullish_engulfing(prev, curr):
            return True, "bullish engulfing"
        if _is_hammer(curr):
            return True, "hammer"
        if _is_bullish_pin_bar(curr):
            return True, "bullish pin bar"
        return False, ""

    def _has_strong_sell(candles):
        if len(candles) < 2:
            return False, ""
        prev, curr = candles[-2], candles[-1]
        if _is_bearish_engulfing(prev, curr):
            return True, "bearish engulfing"
        if _is_shooting_star(curr):
            return True, "shooting star"
        if _is_bearish_pin_bar(curr):
            return True, "bearish pin bar"
        return False, ""

    # ── WITH-TREND entry ──
    if trend.direction == "bullish":
        # Price should be near the EMA (within 0.6%)
        pullback_threshold = ema_current * 1.006
        if last_close <= pullback_threshold:
            confirmed, pattern = _check_confirm(_has_buy_confirmation)
            if confirmed:
                return ScalpEntrySignal(
                    direction="buy",
                    entry_price=last_close,
                    reason=f"Trend-scalp buy: {pattern} at M1 EMA({pullback_ema_period}) pullback",
                )

    elif trend.direction == "bearish":
        pullback_threshold = ema_current * 0.994
        if last_close >= pullback_threshold:
            confirmed, pattern = _check_confirm(_has_sell_confirmation)
            if confirmed:
                return ScalpEntrySignal(
                    direction="sell",
                    entry_price=last_close,
                    reason=f"Trend-scalp sell: {pattern} at M1 EMA({pullback_ema_period}) pullback",
                )

    # ── COUNTER-TREND entry (reversal at extremes) ──
    # Only allowed with a strong reversal pattern — no momentum/single candle
    if trend.direction == "bullish":
        # Look for sell reversal (price extended above EMA, showing weakness)
        confirmed, pattern = _check_confirm(_has_strong_sell)
        if confirmed:
            return ScalpEntrySignal(
                direction="sell",
                entry_price=last_close,
                reason=f"Counter-trend sell: {pattern} (reversal against bullish bias)",
            )

    elif trend.direction == "bearish":
        # Look for buy reversal (price extended below EMA, showing strength)
        confirmed, pattern = _check_confirm(_has_strong_buy)
        if confirmed:
            return ScalpEntrySignal(
                direction="buy",
                entry_price=last_close,
                reason=f"Counter-trend buy: {pattern} (reversal against bearish bias)",
            )

    return None
