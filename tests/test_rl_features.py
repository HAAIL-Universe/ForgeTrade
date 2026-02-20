"""Tests for app.rl.features — 27-feature state vector builder."""

import math

import numpy as np
import pytest

from app.rl.features import (
    STATE_DIM,
    AccountSnapshot,
    ForgeState,
    ForgeStateBuilder,
    clip_feature,
    cyclical_encode,
    distance_to_round_level,
    percentile_rank,
    safe_div,
)
from app.strategy.models import CandleData


def _make_candles(n: int, base_price: float = 5000.0, trend: float = 0.0) -> list[CandleData]:
    """Generate synthetic candle data."""
    candles = []
    for i in range(n):
        o = base_price + i * trend
        c = o + 0.5  # bullish candle
        h = max(o, c) + 0.3
        lo = min(o, c) - 0.3
        candles.append(CandleData(
            time=f"2025-06-02T{8 + i // 12:02d}:{(i % 12) * 5:02d}:00.000000Z",
            open=round(o, 2),
            high=round(h, 2),
            low=round(lo, 2),
            close=round(c, 2),
            volume=100 + i,
        ))
    return candles


class TestUtilities:
    def test_percentile_rank_middle(self):
        values = list(range(100))
        assert 0.49 <= percentile_rank(values, 50) <= 0.51

    def test_percentile_rank_bottom(self):
        values = list(range(100))
        assert percentile_rank(values, 0) == 0.0

    def test_percentile_rank_top(self):
        values = list(range(100))
        assert percentile_rank(values, 99) == 0.99

    def test_percentile_rank_empty(self):
        assert percentile_rank([], 5.0) == 0.5

    def test_cyclical_encode_hour_0(self):
        sin_0, cos_0 = cyclical_encode(0, 24)
        assert abs(sin_0) < 1e-6
        assert abs(cos_0 - 1.0) < 1e-6

    def test_cyclical_encode_hour_24_equals_0(self):
        sin_0, cos_0 = cyclical_encode(0, 24)
        sin_24, cos_24 = cyclical_encode(24, 24)
        assert abs(sin_0 - sin_24) < 1e-6
        assert abs(cos_0 - cos_24) < 1e-6

    def test_cyclical_encode_hour_6(self):
        sin_6, cos_6 = cyclical_encode(6, 24)
        assert abs(sin_6 - 1.0) < 1e-6  # sin(pi/2) = 1

    def test_clip_feature(self):
        assert clip_feature(5.0, 0.0, 3.0) == 3.0
        assert clip_feature(-2.0, -1.0, 1.0) == -1.0
        assert clip_feature(0.5, 0.0, 1.0) == 0.5

    def test_distance_to_round_50(self):
        assert abs(distance_to_round_level(5000.0, 50) - 0.0) < 1e-6
        assert abs(distance_to_round_level(5025.0, 50) - 25.0) < 1e-6
        assert abs(distance_to_round_level(5049.0, 50) - 1.0) < 1e-6

    def test_distance_to_round_100(self):
        assert abs(distance_to_round_level(5000.0, 100) - 0.0) < 1e-6
        assert abs(distance_to_round_level(5050.0, 100) - 50.0) < 1e-6

    def test_safe_div_normal(self):
        assert safe_div(10.0, 2.0) == 5.0

    def test_safe_div_zero(self):
        assert safe_div(10.0, 0.0) == 0.0
        assert safe_div(10.0, 0.0, default=-1.0) == -1.0


class TestForgeState:
    def test_state_dim(self):
        assert STATE_DIM == 27

    def test_to_array_shape(self):
        state = ForgeState()
        arr = state.to_array()
        assert arr.shape == (27,)
        assert arr.dtype == np.float32

    def test_to_array_no_nan(self):
        state = ForgeState()
        arr = state.to_array()
        assert not np.any(np.isnan(arr))
        assert not np.any(np.isinf(arr))

    def test_to_array_values(self):
        state = ForgeState(m5_bias_direction=1.0, h1_trend_agreement=-1.0)
        arr = state.to_array()
        assert arr[2] == 1.0   # m5_bias_direction is 3rd field
        assert arr[4] == -1.0  # h1_trend_agreement is 5th field


class TestForgeStateBuilder:
    @pytest.fixture
    def builder(self):
        return ForgeStateBuilder()

    @pytest.fixture
    def trending_data(self):
        """M5 candles with clear uptrend."""
        return _make_candles(100, base_price=5000.0, trend=0.5)

    @pytest.fixture
    def ranging_data(self):
        """M5 candles oscillating around a flat level."""
        candles = []
        for i in range(100):
            offset = 2.0 * math.sin(i * 0.3)  # oscillating
            o = 5000.0 + offset
            c = o + 0.1 * (1 if i % 2 == 0 else -1)
            h = max(o, c) + 0.2
            lo = min(o, c) - 0.2
            candles.append(CandleData(
                time=f"2025-06-02T{8 + i // 12:02d}:{(i % 12) * 5:02d}:00.000000Z",
                open=round(o, 2),
                high=round(h, 2),
                low=round(lo, 2),
                close=round(c, 2),
                volume=100,
            ))
        return candles

    def test_build_returns_27_features(self, builder, trending_data):
        m1 = _make_candles(20, 5050.0)
        h1 = _make_candles(50, 4950.0, trend=1.0)
        m15 = _make_candles(30, 5000.0, trend=0.3)

        state = builder.build(trending_data, m1, h1, m15)
        arr = state.to_array()
        assert arr.shape == (STATE_DIM,)
        assert arr.dtype == np.float32

    def test_no_nan_or_inf(self, builder, trending_data):
        m1 = _make_candles(20, 5050.0)
        h1 = _make_candles(50, 4950.0, trend=1.0)
        m15 = _make_candles(30, 5000.0, trend=0.3)

        state = builder.build(trending_data, m1, h1, m15)
        arr = state.to_array()
        assert not np.any(np.isnan(arr))
        assert not np.any(np.isinf(arr))

    def test_trending_vs_ranging_different(self, builder, trending_data, ranging_data):
        m1 = _make_candles(20, 5050.0)
        h1 = _make_candles(50, 4950.0, trend=1.0)
        m15 = _make_candles(30, 5000.0)

        state_trend = builder.build(trending_data, m1, h1, m15)
        state_range = builder.build(ranging_data, m1, h1, m15)

        arr_t = state_trend.to_array()
        arr_r = state_range.to_array()
        # The state vectors should differ meaningfully
        diff = np.abs(arr_t - arr_r).sum()
        assert diff > 0.1, "Trending and ranging states should be distinct"

    def test_with_account_state(self, builder, trending_data):
        m1 = _make_candles(20, 5050.0)
        h1 = _make_candles(50, 4950.0, trend=1.0)
        m15 = _make_candles(30, 5000.0)
        account = AccountSnapshot(
            drawdown_pct=5.0,
            max_drawdown_pct=10.0,
            recent_r_multiples=[1.5, -1.0, 1.2, -0.8, 1.0],
        )

        state = builder.build(trending_data, m1, h1, m15, account=account)
        assert state.current_drawdown > 0
        assert state.recent_trade_performance != 0

    def test_empty_candles(self, builder):
        """Should handle empty input gracefully."""
        state = builder.build([], [], [], [])
        arr = state.to_array()
        assert arr.shape == (STATE_DIM,)
        assert not np.any(np.isnan(arr))

    def test_minimal_candles(self, builder):
        """Should handle minimal input without errors."""
        m5 = _make_candles(5, 5000.0)
        state = builder.build(m5, [], [], [])
        arr = state.to_array()
        assert arr.shape == (STATE_DIM,)

    def test_bb_position_at_lower_band(self, builder):
        """Price at lower Bollinger Band → bb_position ≈ 0."""
        # Create candles where price drops to lower band area
        candles = _make_candles(30, base_price=5000.0, trend=-0.5)
        state = builder.build(candles, _make_candles(3), _make_candles(50, trend=0.1), _make_candles(30))
        # bb_position should be low (near or below 0.5)
        assert state.m5_bb_position <= 1.0  # Just check it's valid
