"""Entry signal evaluation — pure functions, no I/O.

Given 4H candles and S/R zones, detects rejection wick patterns at zones
and produces entry signals.
"""

from typing import Optional

from app.strategy.models import CandleData, EntrySignal, SRZone


def _is_rejection_wick_buy(candle: CandleData) -> bool:
    """Check if a candle has a bullish rejection wick (buy signal).

    Criteria: lower wick length > 50% of the candle body.
    A bullish rejection wick has a long lower shadow.
    """
    body = abs(candle.close - candle.open)
    if body == 0:
        # Doji — treat entire range as wick
        lower_wick = candle.close - candle.low  # or open - low (same for doji)
        return lower_wick > 0
    lower_wick = min(candle.open, candle.close) - candle.low
    return lower_wick > 0.5 * body


def _is_rejection_wick_sell(candle: CandleData) -> bool:
    """Check if a candle has a bearish rejection wick (sell signal).

    Criteria: upper wick length > 50% of the candle body.
    A bearish rejection wick has a long upper shadow.
    """
    body = abs(candle.close - candle.open)
    if body == 0:
        upper_wick = candle.high - candle.close
        return upper_wick > 0
    upper_wick = candle.high - max(candle.open, candle.close)
    return upper_wick > 0.5 * body


def _candle_touches_zone(
    candle: CandleData, zone: SRZone, tolerance_pips: float = 15.0
) -> bool:
    """Check if a candle's range touches (or penetrates) an S/R zone.

    A candle touches a zone if the zone price is within the candle's
    high-low range (with a small tolerance in pips).
    """
    pip = 0.0001
    tolerance = tolerance_pips * pip
    return (candle.low - tolerance) <= zone.price_level <= (candle.high + tolerance)


def evaluate_signal(
    candles_4h: list[CandleData],
    sr_zones: list[SRZone],
    tolerance_pips: float = 15.0,
) -> Optional[EntrySignal]:
    """Evaluate the most recent completed 4H candle for an entry signal.

    Logic:
        1. Take the last completed candle.
        2. Check if it touches any S/R zone.
        3. If it touches a support zone, check for a bullish rejection wick → buy.
        4. If it touches a resistance zone, check for a bearish rejection wick → sell.
        5. If multiple zones are touched, pick the one closest to candle close.

    Args:
        candles_4h: Recent 4H candle data (at least 1 candle).
        sr_zones: Current S/R zones.
        tolerance_pips: Tolerance for zone touch detection.

    Returns:
        ``EntrySignal`` if a valid setup is found, else ``None``.
    """
    if not candles_4h or not sr_zones:
        return None

    candle = candles_4h[-1]

    # Find all zones this candle touches
    touched: list[SRZone] = [
        z for z in sr_zones if _candle_touches_zone(candle, z, tolerance_pips)
    ]

    if not touched:
        return None

    # Sort by distance to candle close (closest zone first)
    touched.sort(key=lambda z: abs(z.price_level - candle.close))

    for zone in touched:
        if zone.zone_type == "support" and _is_rejection_wick_buy(candle):
            return EntrySignal(
                direction="buy",
                entry_price=candle.close,
                sr_zone=zone,
                candle_time=candle.time,
                reason=f"Bullish rejection wick at support {zone.price_level:.5f}",
            )
        if zone.zone_type == "resistance" and _is_rejection_wick_sell(candle):
            return EntrySignal(
                direction="sell",
                entry_price=candle.close,
                sr_zone=zone,
                candle_time=candle.time,
                reason=f"Bearish rejection wick at resistance {zone.price_level:.5f}",
            )

    return None
