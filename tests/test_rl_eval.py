"""Tests for app.rl.evaluate — Evaluation protocols."""

import pytest
import numpy as np
from unittest.mock import MagicMock, patch

from app.rl.evaluate import (
    evaluate_agent,
    evaluate_baseline,
    evaluate_holdout,
    walk_forward_splits,
    tag_regime,
    HOLDOUT_THRESHOLDS,
    _slice_aligned_data,
)
from app.rl.environment import AlignedData
from app.strategy.models import CandleData


def _h1_candles(n: int, trend: float = 0.0) -> list[CandleData]:
    cs = []
    for i in range(n):
        p = 5000.0 + i * trend
        cs.append(CandleData(
            time=f"2025-01-01T{i % 24:02d}:00:00Z",
            open=round(p, 2), high=round(p + abs(trend) * 0.3 + 0.5, 2),
            low=round(p - abs(trend) * 0.3 - 0.5, 2), close=round(p + trend * 0.5, 2),
            volume=200,
        ))
    return cs


class TestWalkForwardSplits:
    def test_generates_splits(self):
        splits = walk_forward_splits(1000, train_months=6, test_months=1, total_months=12)
        assert len(splits) == 6  # 12 - 6 = 6 splits

    def test_splits_non_overlapping_test(self):
        splits = walk_forward_splits(1000)
        for i in range(len(splits) - 1):
            # Test windows step forward
            assert splits[i + 1][2] >= splits[i][2]

    def test_all_splits_in_range(self):
        splits = walk_forward_splits(1000)
        for tr_s, tr_e, te_s, te_e in splits:
            assert 0.0 <= tr_s < tr_e <= 1.0
            assert 0.0 <= te_s < te_e <= 1.0


class TestSliceAlignedData:
    def test_slice(self):
        data = AlignedData(
            m1=list(range(100)),
            m5=list(range(50)),
            m15=list(range(20)),
            h1=list(range(10)),
        )
        sliced = _slice_aligned_data(data, 0.2, 0.8)
        assert len(sliced.m1) == 60
        assert len(sliced.m5) == 30
        assert len(sliced.m15) == 12
        assert len(sliced.h1) == 6

    def test_full_slice(self):
        data = AlignedData(m1=list(range(100)), m5=[], m15=[], h1=[])
        sliced = _slice_aligned_data(data, 0.0, 1.0)
        assert len(sliced.m1) == 100


class TestTagRegime:
    def test_trending_up(self):
        candles = _h1_candles(120, trend=3.0)  # Strong uptrend over 120 candles
        regime = tag_regime(candles, window=50)
        assert regime in ["trending_up", "high_volatility"]

    def test_trending_down(self):
        candles = _h1_candles(120, trend=-3.0)
        regime = tag_regime(candles, window=50)
        assert regime in ["trending_down", "high_volatility"]

    def test_ranging(self):
        candles = _h1_candles(60, trend=0.0)
        regime = tag_regime(candles)
        assert regime in ["ranging", "low_volatility"]

    def test_insufficient_data(self):
        candles = _h1_candles(5)
        regime = tag_regime(candles)
        assert regime == "unknown"


class TestEvaluateAgent:
    def test_returns_expected_keys(self):
        """evaluate_agent returns all required metric keys."""
        model = MagicMock()
        model.predict.return_value = (1, None)  # Always TAKE

        env = MagicMock()
        env.reset.return_value = (np.zeros(27, dtype=np.float32), {})
        # Return done=True after one step
        env.step.return_value = (
            np.zeros(27, dtype=np.float32),
            0.5,
            True,
            False,
            {"r_multiple": 0.8, "max_dd": 1.0},
        )

        metrics = evaluate_agent(model, env, n_episodes=3)

        expected_keys = ["win_rate", "take_rate", "profit_factor", "max_drawdown",
                         "avg_r_multiple", "sharpe_ratio", "total_trades_taken"]
        for key in expected_keys:
            assert key in metrics, f"Missing key: {key}"

    def test_all_wins(self):
        """All winning trades → high win rate."""
        model = MagicMock()
        model.predict.return_value = (1, None)

        env = MagicMock()
        env.reset.return_value = (np.zeros(27, dtype=np.float32), {})
        env.step.return_value = (
            np.zeros(27, dtype=np.float32), 1.0, True, False,
            {"r_multiple": 1.0, "max_dd": 0.0},
        )

        metrics = evaluate_agent(model, env, n_episodes=5)
        assert metrics["win_rate"] == 1.0


class TestHoldoutThresholds:
    def test_default_thresholds_exist(self):
        assert "win_rate" in HOLDOUT_THRESHOLDS
        assert "profit_factor" in HOLDOUT_THRESHOLDS
        assert "max_drawdown" in HOLDOUT_THRESHOLDS

    def test_reasonable_values(self):
        assert 0.5 <= HOLDOUT_THRESHOLDS["win_rate"] <= 0.8
        assert HOLDOUT_THRESHOLDS["profit_factor"] >= 1.0
        assert HOLDOUT_THRESHOLDS["max_drawdown"] <= 15.0
