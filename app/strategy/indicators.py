"""Technical indicators — ATR, EMA. Pure functions, no I/O."""

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


def calculate_ema(candles: list[CandleData], period: int) -> list[float]:
    """Calculate an Exponential Moving Average series.

    Uses the standard EMA formula:
        ``EMA_today = close × k + EMA_yesterday × (1 - k)``
    where ``k = 2 / (period + 1)``.

    Requires at least *period* candles. The first EMA value is seeded
    with the SMA of the first *period* closes.

    Returns the full EMA series (same length as *candles*). Entries
    before the seed period are set to ``float('nan')``.

    Raises ``ValueError`` if fewer than *period* candles are provided.
    """
    if len(candles) < period:
        raise ValueError(
            f"Need at least {period} candles for EMA({period}), "
            f"got {len(candles)}"
        )

    k = 2.0 / (period + 1)
    closes = [c.close for c in candles]
    ema: list[float] = [float("nan")] * len(closes)

    # Seed: SMA of first *period* closes
    seed = sum(closes[:period]) / period
    ema[period - 1] = seed

    for i in range(period, len(closes)):
        ema[i] = closes[i] * k + ema[i - 1] * (1 - k)

    return ema
