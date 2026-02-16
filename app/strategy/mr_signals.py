"""Mean reversion entry signal evaluation — pure functions, no I/O.

Evaluates whether price is at a range boundary with momentum exhaustion
and structural (S/R zone) confirmation.
"""

from dataclasses import dataclass
from typing import Optional

from app.strategy.models import CandleData, SRZone, INSTRUMENT_PIP_VALUES


@dataclass(frozen=True)
class MREntrySignal:
    """A mean-reversion entry signal."""

    direction: str  # "buy" or "sell"
    entry_price: float
    rsi: float
    bb_level: float  # the Bollinger band that was touched
    nearest_zone: SRZone
    reason: str


def evaluate_mr_entry(
    candles_m15: list[CandleData],
    rsi_values: list[float],
    bb_upper: list[float],
    bb_lower: list[float],
    bb_mid: list[float],
    zones: list[SRZone],
    *,
    rsi_oversold: float = 30.0,
    rsi_overbought: float = 70.0,
    zone_tolerance_pips: float = 15.0,
    pip_value: float = 0.0001,
) -> Optional[MREntrySignal]:
    """Evaluate for a mean-reversion entry signal.

    Buy conditions (ALL required):
        1. Price ≤ lower Bollinger Band
        2. RSI < *rsi_oversold*
        3. Price within *zone_tolerance_pips* of a support zone

    Sell conditions (ALL required):
        1. Price ≥ upper Bollinger Band
        2. RSI > *rsi_overbought*
        3. Price within *zone_tolerance_pips* of a resistance zone

    Note: The ADX ranging check is done by the strategy *before* calling
    this function, so it is not duplicated here.

    Returns ``MREntrySignal`` if conditions are met, else ``None``.
    """
    import math

    if not candles_m15 or not zones:
        return None

    price = candles_m15[-1].close
    rsi = rsi_values[-1]
    upper = bb_upper[-1]
    lower = bb_lower[-1]

    # Skip if indicators aren't ready yet
    if math.isnan(rsi) or math.isnan(upper) or math.isnan(lower):
        return None

    tolerance = zone_tolerance_pips * pip_value

    # ── Buy: oversold at range bottom ────────────────────────────────
    if price <= lower and rsi < rsi_oversold:
        support_zones = [
            z for z in zones
            if z.zone_type == "support"
            and abs(z.price_level - price) <= tolerance
        ]
        if support_zones:
            nearest = min(support_zones, key=lambda z: abs(z.price_level - price))
            dist_pips = abs(nearest.price_level - price) / pip_value
            return MREntrySignal(
                direction="buy",
                entry_price=price,
                rsi=round(rsi, 2),
                bb_level=round(lower, 5),
                nearest_zone=nearest,
                reason=(
                    f"Mean-reversion buy: RSI {rsi:.1f} (oversold) at lower BB "
                    f"{lower:.5f}, support {nearest.price_level:.5f} "
                    f"({dist_pips:.1f} pips away)"
                ),
            )

    # ── Sell: overbought at range top ────────────────────────────────
    if price >= upper and rsi > rsi_overbought:
        resistance_zones = [
            z for z in zones
            if z.zone_type == "resistance"
            and abs(z.price_level - price) <= tolerance
        ]
        if resistance_zones:
            nearest = min(resistance_zones, key=lambda z: abs(z.price_level - price))
            dist_pips = abs(nearest.price_level - price) / pip_value
            return MREntrySignal(
                direction="sell",
                entry_price=price,
                rsi=round(rsi, 2),
                bb_level=round(upper, 5),
                nearest_zone=nearest,
                reason=(
                    f"Mean-reversion sell: RSI {rsi:.1f} (overbought) at upper BB "
                    f"{upper:.5f}, resistance {nearest.price_level:.5f} "
                    f"({dist_pips:.1f} pips away)"
                ),
            )

    return None
