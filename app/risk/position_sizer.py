"""Position sizing — pure math, no I/O.

Calculates the number of units to trade based on account equity,
risk percentage, stop-loss distance, and pip value.
"""


def calculate_units(
    equity: float,
    risk_pct: float,
    sl_distance_pips: float,
    pip_value: float = 0.0001,
) -> float:
    """Calculate position size in units.

    Formula::

        risk_amount  = equity × (risk_pct / 100)
        sl_in_price  = sl_distance_pips × pip_value
        units        = risk_amount / sl_in_price

    Args:
        equity: Current account equity (e.g. 10_000.0).
        risk_pct: Percentage of equity to risk per trade (e.g. 1.0 for 1 %).
        sl_distance_pips: Stop-loss distance in pips (e.g. 30).
        pip_value: Value of one pip per unit.  Default 0.0001 (EUR/USD).

    Returns:
        Position size in units (always positive).

    Raises:
        ValueError: If any input is non-positive.
    """
    if equity <= 0:
        raise ValueError(f"equity must be positive, got {equity}")
    if risk_pct <= 0:
        raise ValueError(f"risk_pct must be positive, got {risk_pct}")
    if sl_distance_pips <= 0:
        raise ValueError(f"sl_distance_pips must be positive, got {sl_distance_pips}")
    if pip_value <= 0:
        raise ValueError(f"pip_value must be positive, got {pip_value}")

    risk_amount = equity * (risk_pct / 100.0)
    sl_in_price = sl_distance_pips * pip_value
    return risk_amount / sl_in_price
