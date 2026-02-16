"""Technical indicators — ATR, EMA, RSI, ADX, Bollinger Bands. Pure functions, no I/O."""

import math

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


# ── RSI ──────────────────────────────────────────────────────────────────


def calculate_rsi(candles: list[CandleData], period: int = 14) -> list[float]:
    """Calculate Wilder's Relative Strength Index.

    Algorithm (Wilder-smoothed):
        1. delta = close[i] - close[i-1]
        2. Separate gains (positive) and losses (|negative|).
        3. Seed average gain/loss = SMA of first *period* deltas.
        4. Subsequent: avg = (prev_avg × (period-1) + current) / period
        5. RS = avg_gain / avg_loss
        6. RSI = 100 - 100 / (1 + RS)

    Requires at least ``period + 1`` candles.

    Returns a list the same length as *candles*.  Entries before the
    seed period are ``float('nan')``.
    """
    if len(candles) < period + 1:
        raise ValueError(
            f"Need at least {period + 1} candles for RSI({period}), "
            f"got {len(candles)}"
        )

    closes = [c.close for c in candles]
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [max(d, 0.0) for d in deltas]
    losses = [abs(min(d, 0.0)) for d in deltas]

    rsi: list[float] = [float("nan")] * len(candles)

    # Seed averages (SMA of first *period* values)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from_avgs(ag: float, al: float) -> float:
        if al == 0:
            return 100.0
        rs = ag / al
        return 100.0 - 100.0 / (1.0 + rs)

    rsi[period] = _rsi_from_avgs(avg_gain, avg_loss)

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        # Index in rsi is i+1 because deltas are offset by 1
        rsi[i + 1] = _rsi_from_avgs(avg_gain, avg_loss)

    return rsi


# ── ADX ──────────────────────────────────────────────────────────────────


def calculate_adx(candles: list[CandleData], period: int = 14) -> list[float]:
    """Calculate the Average Directional Index (ADX).

    Algorithm:
        1. +DM / -DM directional movement per bar.
        2. Wilder-smooth +DM, -DM, and TR over *period*.
        3. +DI = 100 × smoothed_+DM / smoothed_TR
        4. -DI = 100 × smoothed_-DM / smoothed_TR
        5. DX = 100 × |+DI − −DI| / (+DI + −DI)
        6. ADX = Wilder-smoothed DX over *period*.

    Requires at least ``2 × period + 1`` candles.

    Returns a list the same length as *candles*.  Entries before
    the ADX is ready are ``float('nan')``.
    """
    min_candles = 2 * period + 1
    if len(candles) < min_candles:
        raise ValueError(
            f"Need at least {min_candles} candles for ADX({period}), "
            f"got {len(candles)}"
        )

    n = len(candles)

    # Step 1: raw +DM, -DM, TR per bar (index 0 is unused / nan)
    plus_dm_raw: list[float] = [0.0]
    minus_dm_raw: list[float] = [0.0]
    tr_raw: list[float] = [0.0]

    for i in range(1, n):
        high = candles[i].high
        low = candles[i].low
        prev_high = candles[i - 1].high
        prev_low = candles[i - 1].low
        prev_close = candles[i - 1].close

        up_move = high - prev_high
        down_move = prev_low - low

        pdm = up_move if (up_move > down_move and up_move > 0) else 0.0
        mdm = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))

        plus_dm_raw.append(pdm)
        minus_dm_raw.append(mdm)
        tr_raw.append(tr)

    # Step 2: Wilder-smooth +DM, -DM, TR — seed with SMA of first period
    # Indices 1..period for the seed
    smoothed_plus_dm = sum(plus_dm_raw[1 : period + 1])
    smoothed_minus_dm = sum(minus_dm_raw[1 : period + 1])
    smoothed_tr = sum(tr_raw[1 : period + 1])

    # Step 3-5: compute DI and DX series
    dx_values: list[float] = []

    def _compute_dx(s_pdm: float, s_mdm: float, s_tr: float) -> float:
        if s_tr == 0:
            return 0.0
        plus_di = 100.0 * s_pdm / s_tr
        minus_di = 100.0 * s_mdm / s_tr
        di_sum = plus_di + minus_di
        if di_sum == 0:
            return 0.0
        return 100.0 * abs(plus_di - minus_di) / di_sum

    dx_values.append(_compute_dx(smoothed_plus_dm, smoothed_minus_dm, smoothed_tr))

    for i in range(period + 1, n):
        smoothed_plus_dm = smoothed_plus_dm - smoothed_plus_dm / period + plus_dm_raw[i]
        smoothed_minus_dm = smoothed_minus_dm - smoothed_minus_dm / period + minus_dm_raw[i]
        smoothed_tr = smoothed_tr - smoothed_tr / period + tr_raw[i]
        dx_values.append(
            _compute_dx(smoothed_plus_dm, smoothed_minus_dm, smoothed_tr)
        )

    # Step 6: Wilder-smooth the DX series to get ADX
    # Need *period* DX values for the seed
    adx_result: list[float] = [float("nan")] * n

    # DX series starts at candle index *period* (0-based in dx_values)
    # We need period DX values before we can compute ADX seed
    # dx_values[0] corresponds to candle index *period*
    # So ADX seed uses dx_values[0..period-1], placed at candle index 2*period
    if len(dx_values) < period:
        return adx_result  # not enough data (shouldn't happen given guard)

    adx_seed = sum(dx_values[:period]) / period
    # dx_values[period-1] corresponds to candle index (period + period - 1)
    adx_result[2 * period - 1] = adx_seed

    adx_prev = adx_seed
    for j in range(period, len(dx_values)):
        adx_val = (adx_prev * (period - 1) + dx_values[j]) / period
        adx_result[period + j] = adx_val
        adx_prev = adx_val

    return adx_result


# ── Bollinger Bands ──────────────────────────────────────────────────────


def calculate_bollinger(
    candles: list[CandleData],
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
    """Calculate Bollinger Bands.

    Middle = SMA(close, *period*)
    Upper  = middle + *std_dev* × σ
    Lower  = middle − *std_dev* × σ

    Requires at least *period* candles.

    Returns ``(upper, middle, lower)`` — each list has the same length
    as *candles*.  Entries before the seed period are ``float('nan')``.
    """
    if len(candles) < period:
        raise ValueError(
            f"Need at least {period} candles for Bollinger({period}), "
            f"got {len(candles)}"
        )

    closes = [c.close for c in candles]
    n = len(closes)

    upper: list[float] = [float("nan")] * n
    middle: list[float] = [float("nan")] * n
    lower: list[float] = [float("nan")] * n

    for i in range(period - 1, n):
        window = closes[i - period + 1 : i + 1]
        sma = sum(window) / period
        variance = sum((x - sma) ** 2 for x in window) / period
        sigma = math.sqrt(variance)

        middle[i] = sma
        upper[i] = sma + std_dev * sigma
        lower[i] = sma - std_dev * sigma

    return upper, middle, lower
