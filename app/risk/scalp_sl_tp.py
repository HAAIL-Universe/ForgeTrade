"""Scalp-specific SL/TP calculations.

SL uses recent M5 swing structure.  TP uses fixed risk-reward ratio.
"""

from app.strategy.models import CandleData


# ── SL/TP bounds for gold scalps ─────────────────────────────────────────

MIN_SL_PIPS: float = 200.0  # $2.00 on XAU_USD — avoids noise stopouts
MAX_SL_PIPS: float = 800.0  # $8.00 on XAU_USD — M5 swings are wider than M1


def _find_swing_lows(
    candles: list[CandleData],
    window: int = 2,
) -> list[float]:
    """Return swing-low prices (local minima within ±window bars)."""
    lows: list[float] = []
    for i in range(window, len(candles) - window):
        is_low = all(
            candles[i].low <= candles[i + j].low
            for j in range(-window, window + 1)
            if j != 0
        )
        if is_low:
            lows.append(candles[i].low)
    return lows


def _find_swing_highs(
    candles: list[CandleData],
    window: int = 2,
) -> list[float]:
    """Return swing-high prices (local maxima within ±window bars)."""
    highs: list[float] = []
    for i in range(window, len(candles) - window):
        is_high = all(
            candles[i].high >= candles[i + j].high
            for j in range(-window, window + 1)
            if j != 0
        )
        if is_high:
            highs.append(candles[i].high)
    return highs


def calculate_scalp_sl(
    entry_price: float,
    direction: str,
    candles_m1: list[CandleData],
    pip_value: float = 0.01,
    buffer_pips: float = 30.0,
    lookback: int = 10,
) -> float | None:
    """Calculate scalp SL from M5 swing structure.

    Args:
        entry_price: Entry price.
        direction: ``"buy"`` or ``"sell"``.
        candles_m1: M5 candle history, oldest-first (parameter name kept for compatibility).
        pip_value: Value of 1 pip (0.01 for XAU_USD).
        buffer_pips: Pips beyond the swing level ($0.30 default — gold wicks sweep swings).
        lookback: Number of recent candles to consider.

    Returns:
        SL price, or ``None`` if the resulting SL is outside min/max bounds.
    """
    recent = candles_m1[-lookback:] if len(candles_m1) >= lookback else candles_m1

    if direction == "buy":
        swings = _find_swing_lows(recent, window=2)
        if not swings:
            # Fallback: use lowest low of recent candles
            sl = min(c.low for c in recent) - buffer_pips * pip_value
        else:
            sl = min(swings) - buffer_pips * pip_value
        sl_pips = abs(entry_price - sl) / pip_value
    elif direction == "sell":
        swings = _find_swing_highs(recent, window=2)
        if not swings:
            sl = max(c.high for c in recent) + buffer_pips * pip_value
        else:
            sl = max(swings) + buffer_pips * pip_value
        sl_pips = abs(sl - entry_price) / pip_value
    else:
        return None

    if sl_pips < MIN_SL_PIPS or sl_pips > MAX_SL_PIPS:
        return None

    return round(sl, 2)


def calculate_scalp_tp(
    entry_price: float,
    direction: str,
    sl_price: float,
    rr_ratio: float = 3.0,
) -> float:
    """Calculate scalp TP using fixed risk-reward ratio.

    Args:
        entry_price: Entry price.
        direction: ``"buy"`` or ``"sell"``.
        sl_price: Stop-loss price.
        rr_ratio: Risk:Reward ratio (default 3.0).

    Returns:
        Take-profit price.
    """
    risk = abs(entry_price - sl_price)
    if direction == "buy":
        return round(entry_price + risk * rr_ratio, 2)
    else:
        return round(entry_price - risk * rr_ratio, 2)
