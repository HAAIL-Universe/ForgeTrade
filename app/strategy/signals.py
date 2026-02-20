"""Entry signal evaluation — pure functions, no I/O.

Given 4H candles and S/R zones, detects rejection wick patterns at zones
and produces entry signals.

Direction is determined by **dynamic zone role**: where the candle closes
relative to the zone price decides whether the zone is acting as support
(price above → buy) or resistance (price below → sell).  This captures
S/R role-reversal — a former resistance level that price has broken above
now acts as support, and vice-versa.
"""

from typing import Optional

from app.strategy.models import CandleData, EntrySignal, SRZone


# ── Wick ratio ───────────────────────────────────────────────────────────
# A genuine rejection wick should be at least this many times the candle
# body.  0.5 was the original value; 1.0 is a tighter but still
# reasonable default that filters out ambiguous candles.
DEFAULT_WICK_RATIO = 1.0


def _is_rejection_wick_buy(
    candle: CandleData,
    wick_ratio: float = DEFAULT_WICK_RATIO,
) -> bool:
    """Check if a candle has a bullish rejection wick (buy signal).

    Criteria: lower wick length > *wick_ratio* × candle body.
    A bullish rejection wick has a long lower shadow.
    """
    body = abs(candle.close - candle.open)
    if body == 0:
        # Doji — treat entire range as wick
        lower_wick = candle.close - candle.low
        return lower_wick > 0
    lower_wick = min(candle.open, candle.close) - candle.low
    return lower_wick > wick_ratio * body


def _is_rejection_wick_sell(
    candle: CandleData,
    wick_ratio: float = DEFAULT_WICK_RATIO,
) -> bool:
    """Check if a candle has a bearish rejection wick (sell signal).

    Criteria: upper wick length > *wick_ratio* × candle body.
    A bearish rejection wick has a long upper shadow.
    """
    body = abs(candle.close - candle.open)
    if body == 0:
        upper_wick = candle.high - candle.close
        return upper_wick > 0
    upper_wick = candle.high - max(candle.open, candle.close)
    return upper_wick > wick_ratio * body


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
    min_strength: int = 1,
    wick_ratio: float = DEFAULT_WICK_RATIO,
    trend_direction: Optional[str] = None,
) -> Optional[EntrySignal]:
    """Evaluate the most recent completed 4H candle for an entry signal.

    Uses **dynamic zone role** to determine trade direction:

    * If the candle closes **above** a zone → the zone is acting as
      *support* → look for a bullish rejection wick → **buy**.
    * If the candle closes **below** a zone → the zone is acting as
      *resistance* → look for a bearish rejection wick → **sell**.

    This naturally handles S/R role-reversal (a broken resistance
    becoming support, and vice-versa).

    When *trend_direction* is supplied (``"bullish"``, ``"bearish"``,
    or ``"flat"``), counter-trend signals are blocked:

    * Trend bullish → only **buy** signals allowed.
    * Trend bearish → only **sell** signals allowed.
    * Trend flat / None → both directions allowed.

    Args:
        candles_4h: Recent 4H candle data (at least 1 candle).
        sr_zones: Current S/R zones.
        tolerance_pips: Tolerance for zone touch detection.
        min_strength: Minimum zone touches to consider (filters noise).
        wick_ratio: Minimum wick-to-body ratio for rejection wick.
        trend_direction: H4 EMA trend (``"bullish"``, ``"bearish"``,
            ``"flat"``, or ``None``).  Counter-trend signals are
            blocked when a directional trend is active.

    Returns:
        ``EntrySignal`` if a valid setup is found, else ``None``.
    """
    if not candles_4h or not sr_zones:
        return None

    candle = candles_4h[-1]

    # Filter zones by minimum strength (quality gate)
    quality_zones = [z for z in sr_zones if z.strength >= min_strength]
    if not quality_zones:
        return None

    # Find all zones this candle touches
    touched: list[SRZone] = [
        z for z in quality_zones
        if _candle_touches_zone(candle, z, tolerance_pips)
    ]

    if not touched:
        return None

    # Sort by distance to candle close (closest zone first)
    touched.sort(key=lambda z: abs(z.price_level - candle.close))

    for zone in touched:
        # ── Dynamic zone role ──
        # Where the candle closed relative to the zone determines
        # whether it is acting as support or resistance RIGHT NOW,
        # regardless of how the zone was originally classified.
        if candle.close >= zone.price_level:
            # Price is at or above the zone → zone acts as SUPPORT
            acting_role = "support"
        else:
            # Price is below the zone → zone acts as RESISTANCE
            acting_role = "resistance"

        if acting_role == "support" and _is_rejection_wick_buy(candle, wick_ratio):
            # Trend filter: block buy signals when trend is bearish
            if trend_direction == "bearish":
                continue
            return EntrySignal(
                direction="buy",
                entry_price=candle.close,
                sr_zone=zone,
                candle_time=candle.time,
                reason=(
                    f"Bullish rejection wick at "
                    f"{'support' if zone.zone_type == 'support' else 'flipped support'}"
                    f" {zone.price_level:.5f}"
                ),
            )
        if acting_role == "resistance" and _is_rejection_wick_sell(candle, wick_ratio):
            # Trend filter: block sell signals when trend is bullish
            if trend_direction == "bullish":
                continue
            return EntrySignal(
                direction="sell",
                entry_price=candle.close,
                sr_zone=zone,
                candle_time=candle.time,
                reason=(
                    f"Bearish rejection wick at "
                    f"{'resistance' if zone.zone_type == 'resistance' else 'flipped resistance'}"
                    f" {zone.price_level:.5f}"
                ),
            )

    return None
