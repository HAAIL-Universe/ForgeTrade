"""ATR (Average True Range) calculation — pure function, no I/O."""

from app.strategy.models import CandleData


def calculate_atr(candles: list[CandleData], period: int = 14) -> float:
    """Calculate the Average True Range over *period* candles.

    Uses the standard True Range definition:
        TR = max(high - low, |high - prev_close|, |low - prev_close|)

    Requires at least ``period + 1`` candles (need a previous close for TR).
    Returns the simple average of the last *period* true ranges.

    Raises ``ValueError`` if insufficient data.
    """
    if len(candles) < period + 1:
        raise ValueError(
            f"Need at least {period + 1} candles for ATR({period}), "
            f"got {len(candles)}"
        )

    true_ranges: list[float] = []
    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    # Use the last *period* true ranges
    recent = true_ranges[-period:]
    return sum(recent) / len(recent)
