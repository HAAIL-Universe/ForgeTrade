"""Mean-reversion SL/TP calculation — pure math, no I/O.

SL is placed beyond the range boundary (Bollinger band or S/R zone).
TP targets the Bollinger midpoint (conservative) or opposite band (aggressive).
"""


def calculate_mr_sl(
    entry_price: float,
    direction: str,
    zone_price: float,
    bb_boundary: float,
    atr: float,
    *,
    atr_multiplier: float = 1.5,
    min_sl_pips: float = 10.0,
    max_sl_pips: float = 50.0,
    pip_value: float = 0.0001,
) -> float | None:
    """Calculate stop-loss for a mean-reversion trade.

    Places SL beyond the nearer of the zone price or BB boundary,
    using *atr_multiplier* × ATR as cushion.

    Returns the SL price (rounded to 5dp), or ``None`` if the
    calculated SL falls outside the [min, max] pip bounds — indicating
    the range is too tight or too wide for this strategy.

    Args:
        entry_price: Trade entry price.
        direction: ``"buy"`` or ``"sell"``.
        zone_price: The S/R zone that confirmed the entry.
        bb_boundary: The Bollinger Band touched (lower for buy, upper for sell).
        atr: Current ATR(14) value.
        atr_multiplier: ATR multiplier for cushion (default 1.5).
        min_sl_pips: Minimum SL distance in pips.
        max_sl_pips: Maximum SL distance in pips.
        pip_value: Pip size for the instrument.

    Returns:
        SL price or ``None`` if outside bounds.

    Raises:
        ValueError: If *direction* is not ``"buy"`` or ``"sell"``.
    """
    cushion = atr_multiplier * atr
    # Use the more conservative (further from entry) boundary
    if direction == "buy":
        boundary = min(zone_price, bb_boundary)
        sl = boundary - cushion
    elif direction == "sell":
        boundary = max(zone_price, bb_boundary)
        sl = boundary + cushion
    else:
        raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

    sl_distance_pips = abs(entry_price - sl) / pip_value

    if sl_distance_pips < min_sl_pips or sl_distance_pips > max_sl_pips:
        return None

    return round(sl, 5)


def calculate_mr_tp(
    entry_price: float,
    direction: str,
    bb_mid: float,
) -> float:
    """Calculate take-profit for a mean-reversion trade.

    Conservative target: Bollinger middle band (SMA midpoint of the range).

    Args:
        entry_price: Trade entry price.
        direction: ``"buy"`` or ``"sell"``.
        bb_mid: Bollinger middle band value (SMA).

    Returns:
        TP price rounded to 5 decimal places.

    Raises:
        ValueError: If *direction* is not ``"buy"`` or ``"sell"``.
    """
    if direction not in ("buy", "sell"):
        raise ValueError(f"direction must be 'buy' or 'sell', got '{direction}'")

    # TP is always the midpoint of the range
    return round(bb_mid, 5)
