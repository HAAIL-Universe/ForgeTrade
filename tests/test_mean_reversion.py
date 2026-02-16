"""Deterministic tests for Phase 12 — Mean Reversion strategy.

Covers: RSI, ADX, Bollinger Bands indicators, range detection,
mean-reversion signal evaluation, SL/TP calculation, strategy
registration and protocol conformance.
"""

import math
import pytest

from app.strategy.models import CandleData, SRZone
from app.strategy.indicators import (
    calculate_adx,
    calculate_bollinger,
    calculate_rsi,
)
from app.strategy.mr_signals import evaluate_mr_entry
from app.strategy.mean_reversion import is_ranging, MeanReversionStrategy
from app.risk.mr_sl_tp import calculate_mr_sl, calculate_mr_tp
from app.strategy.base import StrategyProtocol


# ── Helpers ──────────────────────────────────────────────────────────────


def _c(price: float, time: str = "2025-01-01T00:00:00Z", spread: float = 0.0005) -> CandleData:
    """Quick candle at a given close price with small spread."""
    return CandleData(
        time=time, open=price, high=price + spread,
        low=price - spread, close=price, volume=100,
    )


def _trending_up_candles(n: int = 40, start: float = 1.0800, step: float = 0.0010) -> list[CandleData]:
    """Generate *n* candles in a clear uptrend."""
    candles = []
    for i in range(n):
        price = start + i * step
        candles.append(CandleData(
            time=f"2025-01-01T{i:02d}:00:00Z",
            open=price - step * 0.3,
            high=price + step * 0.5,
            low=price - step * 0.5,
            close=price,
            volume=100,
        ))
    return candles


def _ranging_candles(n: int = 40, center: float = 1.0900, amplitude: float = 0.0030) -> list[CandleData]:
    """Generate *n* candles oscillating in a tight range."""
    import math as _math
    candles = []
    for i in range(n):
        # Sinusoidal oscillation
        offset = amplitude * _math.sin(i * _math.pi / 5)
        price = center + offset
        candles.append(CandleData(
            time=f"2025-01-01T{i:02d}:00:00Z",
            open=price - 0.0003,
            high=price + 0.0008,
            low=price - 0.0008,
            close=price,
            volume=100,
        ))
    return candles


def _falling_candles(n: int = 20, start: float = 1.1000, step: float = 0.0010) -> list[CandleData]:
    """Generate *n* candles in a clear downtrend."""
    candles = []
    for i in range(n):
        price = start - i * step
        candles.append(CandleData(
            time=f"2025-01-01T{i:02d}:00:00Z",
            open=price + step * 0.3,
            high=price + step * 0.5,
            low=price - step * 0.5,
            close=price,
            volume=100,
        ))
    return candles


def _flat_candles(n: int = 20, price: float = 1.0900) -> list[CandleData]:
    """Generate *n* flat (doji-like) candles at the same price."""
    return [
        CandleData(
            time=f"2025-01-01T{i:02d}:00:00Z",
            open=price, high=price + 0.0001,
            low=price - 0.0001, close=price, volume=100,
        )
        for i in range(n)
    ]


# ════════════════════════════════════════════════════════════════════════
# RSI Tests
# ════════════════════════════════════════════════════════════════════════


class TestRSI:
    """Tests for calculate_rsi()."""

    def test_rsi_oversold(self):
        """Steadily dropping prices should produce RSI < 30."""
        candles = _falling_candles(20)
        rsi = calculate_rsi(candles, period=14)
        # Last value should be oversold
        assert not math.isnan(rsi[-1])
        assert rsi[-1] < 30, f"Expected RSI < 30 for downtrend, got {rsi[-1]:.1f}"

    def test_rsi_overbought(self):
        """Steadily rising prices should produce RSI > 70."""
        candles = _trending_up_candles(20)
        rsi = calculate_rsi(candles, period=14)
        assert not math.isnan(rsi[-1])
        assert rsi[-1] > 70, f"Expected RSI > 70 for uptrend, got {rsi[-1]:.1f}"

    def test_rsi_neutral(self):
        """Flat prices should produce RSI near 50."""
        # Alternate up/down so gains ≈ losses
        candles = []
        for i in range(20):
            price = 1.0900 + (0.0005 if i % 2 == 0 else -0.0005)
            candles.append(_c(price, time=f"2025-01-01T{i:02d}:00:00Z"))
        rsi = calculate_rsi(candles, period=14)
        assert not math.isnan(rsi[-1])
        assert 35 < rsi[-1] < 65, f"Expected RSI ~50 for sideways, got {rsi[-1]:.1f}"

    def test_rsi_insufficient_data(self):
        """Should raise ValueError with too few candles."""
        candles = [_c(1.0900)] * 10  # need 15 for RSI(14)
        with pytest.raises(ValueError, match="Need at least 15"):
            calculate_rsi(candles, period=14)

    def test_rsi_length_matches_input(self):
        """Output length should match input length."""
        candles = _trending_up_candles(25)
        rsi = calculate_rsi(candles, period=14)
        assert len(rsi) == len(candles)

    def test_rsi_nan_before_seed(self):
        """Values before the seed period should be NaN."""
        candles = _trending_up_candles(25)
        rsi = calculate_rsi(candles, period=14)
        for i in range(14):
            assert math.isnan(rsi[i]), f"rsi[{i}] should be NaN, got {rsi[i]}"

    def test_rsi_range_0_100(self):
        """All non-NaN RSI values should be between 0 and 100."""
        candles = _trending_up_candles(30)
        rsi = calculate_rsi(candles, period=14)
        for val in rsi:
            if not math.isnan(val):
                assert 0 <= val <= 100, f"RSI out of range: {val}"


# ════════════════════════════════════════════════════════════════════════
# ADX Tests
# ════════════════════════════════════════════════════════════════════════


class TestADX:
    """Tests for calculate_adx()."""

    def test_adx_ranging(self):
        """Oscillating prices should produce low ADX (< 25)."""
        candles = _ranging_candles(40)
        adx = calculate_adx(candles, period=14)
        # Find last non-NaN value
        latest = adx[-1]
        assert not math.isnan(latest), "ADX should be computed for 40 ranging candles"
        assert latest < 25, f"Expected ADX < 25 for ranging market, got {latest:.1f}"

    def test_adx_trending(self):
        """Consistently rising prices should produce high ADX (> 25)."""
        candles = _trending_up_candles(40, step=0.0020)
        adx = calculate_adx(candles, period=14)
        latest = adx[-1]
        assert not math.isnan(latest)
        assert latest > 25, f"Expected ADX > 25 for strong trend, got {latest:.1f}"

    def test_adx_insufficient_data(self):
        """Should raise ValueError with too few candles."""
        candles = [_c(1.0900)] * 20  # need 29 for ADX(14)
        with pytest.raises(ValueError, match="Need at least 29"):
            calculate_adx(candles, period=14)

    def test_adx_length_matches_input(self):
        """Output length should match input length."""
        candles = _trending_up_candles(40)
        adx = calculate_adx(candles, period=14)
        assert len(adx) == len(candles)

    def test_adx_nan_before_seed(self):
        """Values before 2*period - 1 should be NaN."""
        candles = _trending_up_candles(40)
        adx = calculate_adx(candles, period=14)
        for i in range(2 * 14 - 1):
            assert math.isnan(adx[i]), f"adx[{i}] should be NaN, got {adx[i]}"

    def test_adx_non_negative(self):
        """All non-NaN ADX values should be >= 0."""
        candles = _trending_up_candles(40)
        adx = calculate_adx(candles, period=14)
        for val in adx:
            if not math.isnan(val):
                assert val >= 0, f"ADX should be non-negative, got {val}"


# ════════════════════════════════════════════════════════════════════════
# Bollinger Bands Tests
# ════════════════════════════════════════════════════════════════════════


class TestBollinger:
    """Tests for calculate_bollinger()."""

    def test_bollinger_band_order(self):
        """Upper > middle > lower for all non-NaN values."""
        candles = _ranging_candles(30)
        upper, middle, lower = calculate_bollinger(candles, period=20)
        for i in range(len(candles)):
            if not math.isnan(upper[i]):
                assert upper[i] > middle[i] > lower[i], (
                    f"At index {i}: upper={upper[i]}, mid={middle[i]}, lower={lower[i]}"
                )

    def test_bollinger_width_increases_with_volatility(self):
        """Bands should be wider for volatile data than calm data."""
        calm = _flat_candles(25, price=1.0900)
        volatile = _ranging_candles(25, amplitude=0.0050)

        u_calm, m_calm, l_calm = calculate_bollinger(calm, period=20)
        u_vol, m_vol, l_vol = calculate_bollinger(volatile, period=20)

        # Compare last band widths
        calm_width = u_calm[-1] - l_calm[-1]
        vol_width = u_vol[-1] - l_vol[-1]
        assert vol_width > calm_width, (
            f"Volatile width {vol_width:.6f} should exceed calm width {calm_width:.6f}"
        )

    def test_bollinger_insufficient_data(self):
        """Should raise ValueError with too few candles."""
        candles = [_c(1.0900)] * 15  # need 20
        with pytest.raises(ValueError, match="Need at least 20"):
            calculate_bollinger(candles, period=20)

    def test_bollinger_length_matches_input(self):
        """All three band lists should match input length."""
        candles = _ranging_candles(30)
        upper, middle, lower = calculate_bollinger(candles, period=20)
        assert len(upper) == len(middle) == len(lower) == len(candles)

    def test_bollinger_nan_before_seed(self):
        """Values before period should be NaN."""
        candles = _ranging_candles(30)
        upper, middle, lower = calculate_bollinger(candles, period=20)
        for i in range(19):
            assert math.isnan(upper[i])
            assert math.isnan(middle[i])
            assert math.isnan(lower[i])


# ════════════════════════════════════════════════════════════════════════
# Range Detection Tests
# ════════════════════════════════════════════════════════════════════════


class TestIsRanging:
    """Tests for is_ranging()."""

    def test_is_ranging_true(self):
        """ADX below threshold → ranging."""
        adx_values = [float("nan")] * 28 + [18.0]
        assert is_ranging(adx_values, threshold=25.0) is True

    def test_is_ranging_false(self):
        """ADX above threshold → trending."""
        adx_values = [float("nan")] * 28 + [32.0]
        assert is_ranging(adx_values, threshold=25.0) is False

    def test_is_ranging_at_threshold(self):
        """ADX exactly at threshold → trending (not strictly less)."""
        adx_values = [float("nan")] * 28 + [25.0]
        assert is_ranging(adx_values, threshold=25.0) is False

    def test_is_ranging_nan(self):
        """All NaN → not ranging (insufficient data)."""
        adx_values = [float("nan")] * 29
        assert is_ranging(adx_values) is False

    def test_is_ranging_empty(self):
        """Empty list → not ranging."""
        assert is_ranging([]) is False


# ════════════════════════════════════════════════════════════════════════
# MR Signal Evaluation Tests
# ════════════════════════════════════════════════════════════════════════


class TestMRSignals:
    """Tests for evaluate_mr_entry()."""

    def _make_indicators(
        self,
        n: int = 30,
        rsi_last: float = 25.0,
        price_last: float = 1.0800,
        bb_upper_last: float = 1.0900,
        bb_lower_last: float = 1.0800,
        bb_mid_last: float = 1.0850,
    ):
        """Build synthetic candles and indicator arrays for MR signal testing."""
        candles = [_c(1.0850, time=f"2025-01-01T{i:02d}:00:00Z") for i in range(n - 1)]
        candles.append(_c(price_last, time=f"2025-01-01T{n-1:02d}:00:00Z"))

        rsi = [float("nan")] * (n - 1) + [rsi_last]
        bb_upper = [float("nan")] * (n - 1) + [bb_upper_last]
        bb_lower = [float("nan")] * (n - 1) + [bb_lower_last]
        bb_mid = [float("nan")] * (n - 1) + [bb_mid_last]

        return candles, rsi, bb_upper, bb_lower, bb_mid

    def test_mr_buy_signal(self):
        """Buy when price at lower BB + RSI oversold + support zone nearby."""
        zones = [SRZone(zone_type="support", price_level=1.0800, strength=3)]
        candles, rsi, bbu, bbl, bbm = self._make_indicators(
            rsi_last=25.0, price_last=1.0798, bb_lower_last=1.0800,
        )
        result = evaluate_mr_entry(candles, rsi, bbu, bbl, bbm, zones)
        assert result is not None
        assert result.direction == "buy"
        assert "Mean-reversion buy" in result.reason

    def test_mr_sell_signal(self):
        """Sell when price at upper BB + RSI overbought + resistance zone nearby."""
        zones = [SRZone(zone_type="resistance", price_level=1.0900, strength=3)]
        candles, rsi, bbu, bbl, bbm = self._make_indicators(
            rsi_last=75.0, price_last=1.0902, bb_upper_last=1.0900,
        )
        result = evaluate_mr_entry(candles, rsi, bbu, bbl, bbm, zones)
        assert result is not None
        assert result.direction == "sell"
        assert "Mean-reversion sell" in result.reason

    def test_mr_blocked_rsi_neutral(self):
        """No signal when RSI is neutral (between 30 and 70)."""
        zones = [SRZone(zone_type="support", price_level=1.0800, strength=3)]
        candles, rsi, bbu, bbl, bbm = self._make_indicators(
            rsi_last=50.0, price_last=1.0798, bb_lower_last=1.0800,
        )
        result = evaluate_mr_entry(candles, rsi, bbu, bbl, bbm, zones)
        assert result is None

    def test_mr_blocked_no_zone(self):
        """No signal when no S/R zone is within tolerance."""
        # Zone is 50 pips away — well outside the 15-pip tolerance
        zones = [SRZone(zone_type="support", price_level=1.0750, strength=3)]
        candles, rsi, bbu, bbl, bbm = self._make_indicators(
            rsi_last=25.0, price_last=1.0798, bb_lower_last=1.0800,
        )
        result = evaluate_mr_entry(candles, rsi, bbu, bbl, bbm, zones)
        assert result is None

    def test_mr_blocked_not_at_boundary(self):
        """No signal when price is between the bands (not at edge)."""
        zones = [SRZone(zone_type="support", price_level=1.0850, strength=3)]
        candles, rsi, bbu, bbl, bbm = self._make_indicators(
            rsi_last=25.0, price_last=1.0850,
            bb_upper_last=1.0900, bb_lower_last=1.0800,
        )
        result = evaluate_mr_entry(candles, rsi, bbu, bbl, bbm, zones)
        assert result is None

    def test_mr_no_candles(self):
        """No signal with empty candle list."""
        zones = [SRZone(zone_type="support", price_level=1.0800, strength=3)]
        result = evaluate_mr_entry([], [], [], [], [], zones)
        assert result is None

    def test_mr_no_zones(self):
        """No signal with empty zone list."""
        candles, rsi, bbu, bbl, bbm = self._make_indicators(
            rsi_last=25.0, price_last=1.0798, bb_lower_last=1.0800,
        )
        result = evaluate_mr_entry(candles, rsi, bbu, bbl, bbm, [])
        assert result is None


# ════════════════════════════════════════════════════════════════════════
# SL/TP Tests
# ════════════════════════════════════════════════════════════════════════


class TestMRSlTp:
    """Tests for calculate_mr_sl() and calculate_mr_tp()."""

    def test_sl_buy_within_bounds(self):
        """Buy SL should be below entry, within 10-50 pip limits."""
        sl = calculate_mr_sl(
            entry_price=1.0800,
            direction="buy",
            zone_price=1.0800,
            bb_boundary=1.0800,
            atr=0.0010,  # 10 pips ATR
        )
        assert sl is not None
        assert sl < 1.0800
        # 1.5 * 0.0010 = 0.0015 → 15 pips from boundary
        assert abs(1.0800 - sl) == pytest.approx(0.0015, abs=1e-5)

    def test_sl_sell_within_bounds(self):
        """Sell SL should be above entry, within bounds."""
        sl = calculate_mr_sl(
            entry_price=1.0900,
            direction="sell",
            zone_price=1.0900,
            bb_boundary=1.0900,
            atr=0.0010,
        )
        assert sl is not None
        assert sl > 1.0900

    def test_sl_too_tight(self):
        """SL should be None when distance < 10 pips."""
        sl = calculate_mr_sl(
            entry_price=1.0800,
            direction="buy",
            zone_price=1.0800,
            bb_boundary=1.0800,
            atr=0.0003,  # 0.00045 → 4.5 pips — too tight
        )
        assert sl is None

    def test_sl_too_wide(self):
        """SL should be None when distance > 50 pips."""
        sl = calculate_mr_sl(
            entry_price=1.0800,
            direction="buy",
            zone_price=1.0800,
            bb_boundary=1.0800,
            atr=0.0050,  # 0.0075 → 75 pips — too wide
        )
        assert sl is None

    def test_sl_invalid_direction(self):
        """Should raise ValueError for bad direction."""
        with pytest.raises(ValueError, match="direction must be"):
            calculate_mr_sl(1.0800, "long", 1.0800, 1.0800, 0.0010)

    def test_tp_buy_is_midpoint(self):
        """Buy TP should be the Bollinger middle band."""
        tp = calculate_mr_tp(1.0800, "buy", 1.0850)
        assert tp == 1.08500

    def test_tp_sell_is_midpoint(self):
        """Sell TP should be the Bollinger middle band."""
        tp = calculate_mr_tp(1.0900, "sell", 1.0850)
        assert tp == 1.08500

    def test_tp_invalid_direction(self):
        """Should raise ValueError for bad direction."""
        with pytest.raises(ValueError, match="direction must be"):
            calculate_mr_tp(1.0800, "long", 1.0850)


# ════════════════════════════════════════════════════════════════════════
# Strategy Registration & Protocol Tests
# ════════════════════════════════════════════════════════════════════════


class TestStrategyIntegration:
    """Tests for strategy registry and protocol conformance."""

    def test_strategy_registry(self):
        """get_strategy('mean_reversion') should return an instance."""
        from app.strategy.registry import get_strategy
        strat = get_strategy("mean_reversion")
        assert strat is not None

    def test_strategy_protocol(self):
        """MeanReversionStrategy should satisfy StrategyProtocol."""
        strat = MeanReversionStrategy()
        assert isinstance(strat, StrategyProtocol)

    def test_strategy_has_last_insight(self):
        """Strategy should initialise with an empty last_insight dict."""
        strat = MeanReversionStrategy()
        assert strat.last_insight == {}
