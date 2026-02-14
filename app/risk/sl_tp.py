"""Stop-loss and take-profit calculation — pure math, no I/O.

SL is placed at 1.5 × ATR beyond the S/R zone.
TP is the nearer of the next S/R zone or 1:2 risk-reward.
"""

from app.strategy.models import SRZone


def calculate_sl(
    entry_price: float,
    direction: str,
    zone_price: float,
    atr: float,
) -> float:
    """Calculate the stop-loss price.

    Places the SL at 1.5 × ATR beyond the S/R zone in the direction
    that would represent a loss.

    - **Buy**:  SL = zone_price − (1.5 × ATR)   (below support)
    - **Sell**: SL = zone_price + (1.5 × ATR)   (above resistance)

    Args:
        entry_price: Trade entry price (unused in formula but kept for
                     symmetry with ``calculate_tp``).
        direction: ``"buy"`` or ``"sell"``.
        zone_price: The S/R zone price level that triggered the signal.
        atr: Current ATR(14) value.

    Returns:
        Stop-loss price rounded to 5 decimal places.

    Raises:
        ValueError: If *direction* is not ``"buy"`` or ``"sell"``.
    """
    if direction == "buy":
        sl = zone_price - (1.5 * atr)
    elif direction == "sell":
        sl = zone_price + (1.5 * atr)
    else:
        raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")
    return round(sl, 5)


def calculate_tp(
    entry_price: float,
    direction: str,
    sl_price: float,
    sr_zones: list[SRZone],
) -> float:
    """Calculate the take-profit price.

    Strategy:
        1. Compute the 1:2 risk-reward target.
        2. Find the nearest S/R zone in the profit direction.
        3. Return whichever is **closer** to entry.

    If no zone exists beyond entry in the profit direction, falls back
    to the 1:2 RR target.

    Args:
        entry_price: Trade entry price.
        direction: ``"buy"`` or ``"sell"``.
        sl_price: Stop-loss price (used to compute risk distance).
        sr_zones: All current S/R zones.

    Returns:
        Take-profit price rounded to 5 decimal places.

    Raises:
        ValueError: If *direction* is not ``"buy"`` or ``"sell"``.
    """
    risk = abs(entry_price - sl_price)

    if direction == "buy":
        rr_tp = entry_price + 2.0 * risk
        # Nearest zone above entry
        zones_above = sorted(
            [z for z in sr_zones if z.price_level > entry_price],
            key=lambda z: z.price_level,
        )
        next_zone_price = zones_above[0].price_level if zones_above else None
    elif direction == "sell":
        rr_tp = entry_price - 2.0 * risk
        # Nearest zone below entry
        zones_below = sorted(
            [z for z in sr_zones if z.price_level < entry_price],
            key=lambda z: -z.price_level,
        )
        next_zone_price = zones_below[0].price_level if zones_below else None
    else:
        raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

    if next_zone_price is None:
        return round(rr_tp, 5)

    # Pick whichever target is closer to entry
    rr_dist = abs(rr_tp - entry_price)
    zone_dist = abs(next_zone_price - entry_price)

    if zone_dist <= rr_dist:
        return round(next_zone_price, 5)
    return round(rr_tp, 5)
