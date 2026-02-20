"""Stop-loss and take-profit calculation — pure math, no I/O.

Zone-anchored approach (primary):
    TP is set at the next S/R zone in the profit direction.
    SL is derived from TP distance ÷ R:R ratio, with ATR-based bounds.

Legacy approach (kept for backward compatibility / backtest):
    SL is placed at 1.5 × ATR beyond the S/R zone.
    TP is the nearer of the next S/R zone or R:R fallback.
"""

from dataclasses import dataclass
from typing import Optional

from app.strategy.models import SRZone


@dataclass
class RiskLevels:
    """Computed stop-loss and take-profit for a trade."""
    sl: float
    tp: float
    tp_source: str  # "zone" or "atr_fallback"


def calculate_zone_anchored_risk(
    entry_price: float,
    direction: str,
    sr_zones: list[SRZone],
    atr: float,
    rr_ratio: float = 2.0,
    triggering_zone: Optional[SRZone] = None,
    min_sl_atr_mult: float = 0.5,
    max_sl_atr_mult: float = 2.0,
    min_tp_atr_mult: float = 1.0,
) -> Optional[RiskLevels]:
    """Calculate SL and TP using the zone-anchored approach.

    Logic:
        1. Find the nearest S/R zone in the profit direction (excluding
           the triggering zone).  This is the TP target.
        2. Derive SL = TP distance ÷ rr_ratio.
        3. Enforce SL bounds:  min_sl = min_sl_atr_mult × ATR,
           max_sl = max_sl_atr_mult × ATR.
        4. If derived SL < min_sl → zone is too close, skip trade.
        5. If derived SL > max_sl → cap SL at max_sl (R:R improves
           beyond the requested ratio — that's fine).
        6. If no zone exists in the profit direction, fall back to
           TP = rr_ratio × max_sl_atr_mult × ATR from entry (ATR-based
           fallback), with SL = max_sl_atr_mult × ATR.

    Args:
        entry_price: Trade entry price.
        direction: ``"buy"`` or ``"sell"``.
        sr_zones: All current S/R zones.
        atr: Current ATR(14) value.
        rr_ratio: Desired risk-reward ratio (default 2.0).
        triggering_zone: The zone that generated the signal (excluded
            from TP candidates).
        min_sl_atr_mult: Minimum SL as a multiple of ATR (default 0.5).
        max_sl_atr_mult: Maximum SL as a multiple of ATR (default 2.0).
        min_tp_atr_mult: Minimum TP distance as a multiple of ATR
            (default 1.0).  Zones closer than this are skipped.

    Returns:
        ``RiskLevels`` with sl, tp, and tp_source.
        ``None`` if no valid setup exists (zone too close = SL < floor).
    """
    if direction not in ("buy", "sell"):
        raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

    min_sl = min_sl_atr_mult * atr
    max_sl = max_sl_atr_mult * atr
    min_tp_dist = min_tp_atr_mult * atr

    # Filter out the triggering zone
    candidates = [
        z for z in sr_zones
        if triggering_zone is None or z.price_level != triggering_zone.price_level
    ]

    # Find nearest valid zone in profit direction
    if direction == "buy":
        valid_zones = sorted(
            [z for z in candidates
             if z.price_level > entry_price
             and (z.price_level - entry_price) >= min_tp_dist],
            key=lambda z: z.price_level,
        )
    else:  # sell
        valid_zones = sorted(
            [z for z in candidates
             if z.price_level < entry_price
             and (entry_price - z.price_level) >= min_tp_dist],
            key=lambda z: -z.price_level,
        )

    if valid_zones:
        # Zone-anchored path
        tp_price = valid_zones[0].price_level
        tp_dist = abs(tp_price - entry_price)
        derived_sl_dist = tp_dist / rr_ratio

        if derived_sl_dist < min_sl:
            # Zone is too close — SL would be absurdly tight. Skip trade.
            return None

        # Cap SL at max to prevent huge risk on distant zones
        sl_dist = min(derived_sl_dist, max_sl)

        if direction == "buy":
            sl_price = entry_price - sl_dist
        else:
            sl_price = entry_price + sl_dist

        return RiskLevels(
            sl=round(sl_price, 5),
            tp=round(tp_price, 5),
            tp_source="zone",
        )
    else:
        # No zone in profit direction — ATR-based fallback
        sl_dist = max_sl
        tp_dist = rr_ratio * sl_dist

        if direction == "buy":
            sl_price = entry_price - sl_dist
            tp_price = entry_price + tp_dist
        else:
            sl_price = entry_price + sl_dist
            tp_price = entry_price - tp_dist

        return RiskLevels(
            sl=round(sl_price, 5),
            tp=round(tp_price, 5),
            tp_source="atr_fallback",
        )


# ── Legacy functions (used by backtest engine) ──────────────────────────


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
    rr_ratio: float = 2.0,
    triggering_zone: Optional[SRZone] = None,
    min_rr: float = 1.0,
) -> float:
    """Calculate the take-profit price.

    Strategy:
        1. Compute the risk-reward target using *rr_ratio*.
        2. Find the nearest S/R zone in the profit direction,
           **excluding** the zone that triggered the signal.
        3. Return whichever is **closer** to entry.
        4. Enforce a minimum risk-reward floor (*min_rr*) — if the
           nearest zone would produce a R:R below the floor, fall
           back to the *min_rr* target.

    If no zone exists beyond entry in the profit direction, falls back
    to the RR target.

    Args:
        entry_price: Trade entry price.
        direction: ``"buy"`` or ``"sell"``.
        sl_price: Stop-loss price (used to compute risk distance).
        sr_zones: All current S/R zones.
        rr_ratio: Risk-reward ratio (default 2.0 = 1:2 R:R).
        triggering_zone: The S/R zone that generated the signal.
            Excluded from TP candidates so TP is never placed at
            the entry zone itself.
        min_rr: Minimum acceptable risk-reward ratio (default 1.0).
            Zone-based TPs closer than ``min_rr × risk`` are rejected
            in favour of the ``min_rr`` target.

    Returns:
        Take-profit price rounded to 5 decimal places.

    Raises:
        ValueError: If *direction* is not ``"buy"`` or ``"sell"``.
    """
    risk = abs(entry_price - sl_price)
    min_tp_dist = min_rr * risk

    # Filter out the triggering zone so TP is never at the entry zone
    candidates = [
        z for z in sr_zones
        if triggering_zone is None or z.price_level != triggering_zone.price_level
    ]

    if direction == "buy":
        rr_tp = entry_price + rr_ratio * risk
        # Nearest valid zone above entry (must exceed min R:R distance)
        zones_above = sorted(
            [z for z in candidates
             if z.price_level > entry_price
             and (z.price_level - entry_price) >= min_tp_dist],
            key=lambda z: z.price_level,
        )
        next_zone_price = zones_above[0].price_level if zones_above else None
    elif direction == "sell":
        rr_tp = entry_price - rr_ratio * risk
        # Nearest valid zone below entry (must exceed min R:R distance)
        zones_below = sorted(
            [z for z in candidates
             if z.price_level < entry_price
             and (entry_price - z.price_level) >= min_tp_dist],
            key=lambda z: -z.price_level,
        )
        next_zone_price = zones_below[0].price_level if zones_below else None
    else:
        raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

    if next_zone_price is None:
        return round(rr_tp, 5)

    # Pick whichever target is closer to entry
    zone_dist = abs(next_zone_price - entry_price)
    rr_dist = abs(rr_tp - entry_price)

    if zone_dist <= rr_dist:
        return round(next_zone_price, 5)
    return round(rr_tp, 5)
