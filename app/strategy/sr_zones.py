"""Support/Resistance zone detection from Daily candles — pure functions."""

from app.strategy.models import CandleData, SRZone


def _find_swing_highs(candles: list[CandleData], window: int = 3) -> list[float]:
    """Identify swing high prices.

    A swing high is a candle whose high is higher than the highs of the
    *window* candles on each side.
    """
    highs: list[float] = []
    for i in range(window, len(candles) - window):
        high = candles[i].high
        is_swing = True
        for j in range(1, window + 1):
            if candles[i - j].high >= high or candles[i + j].high >= high:
                is_swing = False
                break
        if is_swing:
            highs.append(high)
    return highs


def _find_swing_lows(candles: list[CandleData], window: int = 3) -> list[float]:
    """Identify swing low prices.

    A swing low is a candle whose low is lower than the lows of the
    *window* candles on each side.
    """
    lows: list[float] = []
    for i in range(window, len(candles) - window):
        low = candles[i].low
        is_swing = True
        for j in range(1, window + 1):
            if candles[i - j].low <= low or candles[i + j].low <= low:
                is_swing = False
                break
        if is_swing:
            lows.append(low)
    return lows


def _cluster_levels(
    levels: list[float], tolerance_pips: float = 20.0
) -> list[tuple[float, int]]:
    """Cluster nearby price levels into zones.

    Groups levels within *tolerance_pips* of each other.  Returns a list of
    (average_price, touch_count) tuples sorted by price.

    For EUR/USD a pip is 0.0001, so 20 pips = 0.0020.
    """
    pip = 0.0001
    tolerance = tolerance_pips * pip

    if not levels:
        return []

    sorted_levels = sorted(levels)
    clusters: list[list[float]] = []
    current_cluster: list[float] = [sorted_levels[0]]

    for level in sorted_levels[1:]:
        if abs(level - current_cluster[-1]) <= tolerance:
            current_cluster.append(level)
        else:
            clusters.append(current_cluster)
            current_cluster = [level]
    clusters.append(current_cluster)

    return [
        (sum(c) / len(c), len(c))
        for c in clusters
    ]


def detect_sr_zones(
    candles: list[CandleData],
    lookback: int = 50,
    swing_window: int = 3,
    tolerance_pips: float = 20.0,
) -> list[SRZone]:
    """Detect horizontal support and resistance zones from Daily candles.

    Args:
        candles: Daily candle data (should have at least *lookback* candles).
        lookback: Number of most-recent candles to analyse.
        swing_window: Half-window size for swing detection.
        tolerance_pips: Clustering tolerance in pips.

    Returns:
        List of ``SRZone`` objects sorted by price level.
    """
    recent = candles[-lookback:] if len(candles) > lookback else candles

    swing_highs = _find_swing_highs(recent, window=swing_window)
    swing_lows = _find_swing_lows(recent, window=swing_window)

    resistance_clusters = _cluster_levels(swing_highs, tolerance_pips)
    support_clusters = _cluster_levels(swing_lows, tolerance_pips)

    zones: list[SRZone] = []
    for price, strength in resistance_clusters:
        zones.append(
            SRZone(zone_type="resistance", price_level=round(price, 5), strength=strength)
        )
    for price, strength in support_clusters:
        zones.append(
            SRZone(zone_type="support", price_level=round(price, 5), strength=strength)
        )

    zones.sort(key=lambda z: z.price_level)
    return zones
