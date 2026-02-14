"""Deterministic tests for the strategy module.

All tests use fixed candle data fixtures. Same input = same output, always.
"""

import pytest

from app.strategy.models import CandleData, SRZone, EntrySignal
from app.strategy.sr_zones import detect_sr_zones
from app.strategy.signals import evaluate_signal
from app.strategy.session_filter import is_in_session
from app.strategy.indicators import calculate_atr


# ── Candle fixtures ──────────────────────────────────────────────────────

def _make_candle(time: str, o: float, h: float, l: float, c: float, vol: int = 1000) -> CandleData:
    return CandleData(time=time, open=o, high=h, low=l, close=c, volume=vol)


def _daily_candles_with_sr() -> list[CandleData]:
    """50 daily candles with clear swing highs and lows for S/R detection.

    Structure: price oscillates between ~1.0800 (support) and ~1.1000 (resistance),
    with swing highs/lows clearly defined by +-3 candle windows.
    """
    candles = []
    # Create a clear oscillating pattern
    base_prices = [
        # Downswing to support ~1.0800
        1.0950, 1.0930, 1.0900, 1.0870, 1.0840, 1.0810, 1.0800,
        # Upswing from support
        1.0820, 1.0850, 1.0880, 1.0910, 1.0940, 1.0970, 1.1000,
        # Downswing from resistance ~1.1000
        1.0980, 1.0960, 1.0930, 1.0900, 1.0870, 1.0840, 1.0802,
        # Upswing from support
        1.0825, 1.0855, 1.0885, 1.0915, 1.0945, 1.0975, 1.0998,
        # Downswing from resistance
        1.0975, 1.0950, 1.0920, 1.0890, 1.0860, 1.0830, 1.0805,
        # Upswing again
        1.0830, 1.0860, 1.0890, 1.0920, 1.0950, 1.0980, 1.0995,
        # Final down
        1.0970, 1.0940, 1.0910, 1.0880, 1.0850, 1.0820, 1.0808,
        # Tail
        1.0830,
    ]
    for i, base in enumerate(base_prices):
        t = f"2025-01-{i+1:02d}T00:00:00Z"
        spread = 0.0020
        candles.append(_make_candle(t, base, base + spread, base - spread, base))
    return candles


def _four_h_candle_at_support_with_wick() -> list[CandleData]:
    """4H candle touching support at ~1.0800 with bullish rejection wick."""
    return [
        # Previous candles (not tested, just context)
        _make_candle("2025-02-01T00:00:00Z", 1.0850, 1.0860, 1.0840, 1.0845),
        _make_candle("2025-02-01T04:00:00Z", 1.0845, 1.0850, 1.0830, 1.0835),
        # Signal candle: touches support ~1.0800, has bullish rejection wick
        # Body is small (open=1.0820, close=1.0830), lower wick is long (low=1.0795)
        _make_candle("2025-02-01T08:00:00Z", 1.0820, 1.0835, 1.0795, 1.0830),
    ]


def _four_h_candle_at_resistance_with_wick() -> list[CandleData]:
    """4H candle touching resistance at ~1.1000 with bearish rejection wick."""
    return [
        _make_candle("2025-02-01T00:00:00Z", 1.0960, 1.0970, 1.0950, 1.0965),
        _make_candle("2025-02-01T04:00:00Z", 1.0965, 1.0980, 1.0960, 1.0975),
        # Signal candle: touches resistance ~1.1000, bearish rejection wick
        # Body small (open=1.0990, close=1.0980), upper wick long (high=1.1010)
        _make_candle("2025-02-01T08:00:00Z", 1.0990, 1.1010, 1.0975, 1.0980),
    ]


def _four_h_candle_no_zone_touch() -> list[CandleData]:
    """4H candle in the middle, not touching any zone."""
    return [
        _make_candle("2025-02-01T08:00:00Z", 1.0900, 1.0920, 1.0890, 1.0910),
    ]


def _four_h_candle_at_zone_no_wick() -> list[CandleData]:
    """4H candle touches support zone but has NO rejection wick (strong body)."""
    return [
        # Candle touches support ~1.0800, but closes near its low — no wick
        # Big body down, lower wick is 0
        _make_candle("2025-02-01T08:00:00Z", 1.0840, 1.0845, 1.0800, 1.0800),
    ]


# ── ATR fixture ──────────────────────────────────────────────────────────

def _atr_candles() -> list[CandleData]:
    """16 candles for ATR(14) calculation (need 15 = period+1)."""
    # Uniform candles with known ranges for easy manual calculation
    candles = []
    base = 1.0900
    for i in range(16):
        o = base + i * 0.0001
        # Each candle has a range of 0.0020 (high - low)
        h = o + 0.0010
        l = o - 0.0010
        c = o + 0.0002
        candles.append(_make_candle(f"2025-01-{i+1:02d}T00:00:00Z", o, h, l, c))
    return candles


# ── Tests ────────────────────────────────────────────────────────────────


class TestSRZoneDetection:
    def test_sr_zone_detection(self):
        """Correct support/resistance levels from fixture candles."""
        candles = _daily_candles_with_sr()
        zones = detect_sr_zones(candles, lookback=50, swing_window=3, tolerance_pips=25.0)
        assert len(zones) > 0

        support_zones = [z for z in zones if z.zone_type == "support"]
        resistance_zones = [z for z in zones if z.zone_type == "resistance"]

        assert len(support_zones) > 0, "Should detect at least one support zone"
        assert len(resistance_zones) > 0, "Should detect at least one resistance zone"

        # Support zones should be near 1.0800
        for z in support_zones:
            assert 1.0750 < z.price_level < 1.0850, f"Support zone {z.price_level} out of range"

        # Resistance zones should be near 1.1000
        for z in resistance_zones:
            assert 1.0950 < z.price_level < 1.1050, f"Resistance zone {z.price_level} out of range"


class TestSignals:
    def _get_zones(self) -> list[SRZone]:
        """Standard test zones."""
        return [
            SRZone(zone_type="support", price_level=1.0800, strength=3),
            SRZone(zone_type="resistance", price_level=1.1000, strength=2),
        ]

    def test_rejection_wick_buy(self):
        """Buy signal at support with valid rejection wick."""
        candles = _four_h_candle_at_support_with_wick()
        zones = self._get_zones()
        signal = evaluate_signal(candles, zones)

        assert signal is not None
        assert signal.direction == "buy"
        assert signal.sr_zone.zone_type == "support"
        assert signal.sr_zone.price_level == pytest.approx(1.0800)

    def test_rejection_wick_sell(self):
        """Sell signal at resistance with valid rejection wick."""
        candles = _four_h_candle_at_resistance_with_wick()
        zones = self._get_zones()
        signal = evaluate_signal(candles, zones)

        assert signal is not None
        assert signal.direction == "sell"
        assert signal.sr_zone.zone_type == "resistance"
        assert signal.sr_zone.price_level == pytest.approx(1.1000)

    def test_no_signal_no_touch(self):
        """None when price doesn't touch any zone."""
        candles = _four_h_candle_no_zone_touch()
        zones = self._get_zones()
        signal = evaluate_signal(candles, zones)
        assert signal is None

    def test_no_signal_no_wick(self):
        """None when price touches zone but no rejection wick."""
        candles = _four_h_candle_at_zone_no_wick()
        zones = self._get_zones()
        signal = evaluate_signal(candles, zones)
        assert signal is None


class TestSessionFilter:
    def test_session_filter_in(self):
        """True during London/NY overlap."""
        assert is_in_session(12) is True
        assert is_in_session(7) is True
        assert is_in_session(20) is True

    def test_session_filter_out(self):
        """False during Asian session."""
        assert is_in_session(3) is False
        assert is_in_session(0) is False
        assert is_in_session(6) is False
        assert is_in_session(21) is False
        assert is_in_session(23) is False


class TestATR:
    def test_atr_calculation(self):
        """ATR(14) matches expected value for uniform candles."""
        candles = _atr_candles()
        atr = calculate_atr(candles, period=14)
        # Each candle has H-L = 0.0020. Since prices are very close/sequential,
        # TR ≈ max(H-L, |H-prev_close|, |L-prev_close|)
        # For these candles, H-L = 0.002 dominates
        assert atr > 0
        assert atr == pytest.approx(0.002, abs=0.0005)

    def test_atr_insufficient_data(self):
        """Raises ValueError with too few candles."""
        candles = _atr_candles()[:5]  # only 5 candles
        with pytest.raises(ValueError, match="Need at least"):
            calculate_atr(candles, period=14)


class TestDeterminism:
    def test_determinism(self):
        """Two calls with same candles produce identical output."""
        candles = _daily_candles_with_sr()
        zones_1 = detect_sr_zones(candles)
        zones_2 = detect_sr_zones(candles)
        assert zones_1 == zones_2

        candles_4h = _four_h_candle_at_support_with_wick()
        signal_1 = evaluate_signal(candles_4h, zones_1)
        signal_2 = evaluate_signal(candles_4h, zones_2)
        assert signal_1 == signal_2
