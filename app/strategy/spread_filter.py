"""Spread filter — rejects scalp entries when spread is too wide.

The spread is estimated from the most recent S5 candle's high-low range
(a proxy for bid-ask when the candle body is small).
"""


def is_spread_acceptable(
    bid: float,
    ask: float,
    max_spread_pips: float,
    pip_value: float = 0.01,
) -> bool:
    """Return ``True`` if the current spread is within the acceptable limit.

    Args:
        bid: Current bid price.
        ask: Current ask price.
        max_spread_pips: Maximum allowed spread in pips.
        pip_value: Value of 1 pip for the instrument (0.01 for XAU_USD).

    Returns:
        ``True`` if spread ≤ ``max_spread_pips``, else ``False``.
    """
    spread_pips = abs(ask - bid) / pip_value
    return spread_pips <= max_spread_pips


def estimate_spread_from_s5(
    candle_high: float,
    candle_low: float,
    pip_value: float = 0.01,
) -> float:
    """Estimate spread in pips from an S5 candle's high-low range.

    This is an approximation — a very small S5 candle with minimal
    movement will have a range dominated by the bid-ask spread.

    Returns:
        Estimated spread in pips.
    """
    return abs(candle_high - candle_low) / pip_value
