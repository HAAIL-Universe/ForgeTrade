"""Tests for app.rl.train — Training pipeline (smoke tests only)."""

import json
import pytest
import numpy as np
import gymnasium as gym
from pathlib import Path
from unittest.mock import patch, MagicMock

from app.rl.features import STATE_DIM
from app.rl.train import ForgeTrainingCallback, load_training_data, train, MODELS_DIR


class TestForgeTrainingCallback:
    def test_on_step_returns_true(self):
        cb = ForgeTrainingCallback()
        cb._logger = MagicMock()
        cb.locals = {"infos": []}
        assert cb._on_step() is True

    def test_records_forge_metrics(self):
        cb = ForgeTrainingCallback()
        mock_model = MagicMock()
        cb.model = mock_model
        cb.locals = {"infos": [{"take_rate": 0.6, "win_rate": 0.55, "avg_r": 0.4, "max_dd": 3.2}]}
        cb._on_step()
        assert mock_model.logger.record.call_count == 4


class TestLoadTrainingData:
    @patch("app.rl.train.load_from_parquet")
    @patch("pathlib.Path.exists", return_value=True)
    def test_returns_three_aligned_data(self, mock_exists, mock_load):
        """load_training_data returns train, val, test AlignedData tuples."""
        import pandas as pd
        # Create enough rows for a meaningful split
        n = 100
        df = pd.DataFrame({
            "time": [f"2025-01-{(i % 28)+1:02d}T12:00:00Z" for i in range(n)],
            "open": np.random.uniform(4900, 5100, n),
            "high": np.random.uniform(5000, 5200, n),
            "low": np.random.uniform(4800, 5000, n),
            "close": np.random.uniform(4900, 5100, n),
            "volume": np.random.randint(50, 200, n),
        })
        mock_load.return_value = df

        train_d, val_d, test_d = load_training_data("XAU_USD")

        assert len(train_d.m5) > 0
        assert len(train_d.m1) > 0
        assert len(val_d.m5) > 0
        assert len(test_d.m5) > 0


class TestTrainSmoke:
    """Smoke test: ensure training runs for a few steps without crash."""

    @patch("app.rl.train.load_training_data")
    def test_train_minimal(self, mock_load, tmp_path):
        """Train for 100 timesteps on synthetic data — should not crash."""
        from app.rl.environment import AlignedData, EnvConfig
        from app.rl.rewards import RewardConfig
        from app.strategy.models import CandleData

        # Create synthetic candle data
        def _candles(n: int) -> list[CandleData]:
            cs = []
            for i in range(n):
                p = 5000.0 + (i % 20) * 0.5
                cs.append(CandleData(
                    time=f"2025-06-02T{8 + i // 60:02d}:{i % 60:02d}:00.000000Z",
                    open=round(p, 2), high=round(p + 1.0, 2),
                    low=round(p - 1.0, 2), close=round(p + 0.3, 2),
                    volume=100,
                ))
            return cs

        data = AlignedData(
            m1=_candles(500),
            m5=_candles(100),
            m15=_candles(40),
            h1=_candles(20),
        )
        mock_load.return_value = (data, data, data)

        # Override MODELS_DIR to tmp_path
        with patch("app.rl.train.MODELS_DIR", tmp_path / "models"):
            result_path = train(
                instrument="XAU_USD",
                total_timesteps=128,  # Very short
                noise_std=0.01,
                seed=42,
            )
            # Should have saved a model
            assert (tmp_path / "models").exists()
