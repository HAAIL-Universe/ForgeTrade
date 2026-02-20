"""Tests for app.rl.filter — RLTradeFilter and ShadowLogger."""

import json
import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.rl.features import STATE_DIM
from app.rl.filter import RLTradeFilter, ShadowLogger


class TestShadowLogger:
    def test_log_creates_file(self, tmp_path):
        log_path = tmp_path / "shadow.jsonl"
        sl = ShadowLogger(str(log_path))
        sl.log(
            timestamp="2025-06-02T09:00:00Z",
            instrument="XAU_USD",
            direction="buy",
            entry_price=5000.0,
            action=1,
            confidence=0.75,
        )
        assert log_path.exists()

    def test_log_jsonl_format(self, tmp_path):
        log_path = tmp_path / "shadow.jsonl"
        sl = ShadowLogger(str(log_path))
        sl.log("2025-06-02T09:00:00Z", "XAU_USD", "buy", 5000.0, 1, 0.75)
        sl.log("2025-06-02T09:05:00Z", "XAU_USD", "sell", 5010.0, 0, 0.65)

        lines = log_path.read_text().strip().split("\n")
        assert len(lines) == 2
        record1 = json.loads(lines[0])
        assert record1["agent_action"] == "TAKE"
        record2 = json.loads(lines[1])
        assert record2["agent_action"] == "VETO"

    def test_log_outcome(self, tmp_path):
        log_path = tmp_path / "shadow.jsonl"
        sl = ShadowLogger(str(log_path))
        sl.log_outcome(
            timestamp="2025-06-02T09:30:00Z",
            instrument="XAU_USD",
            actual_outcome="tp_hit",
            r_multiple=1.5,
        )
        record = json.loads(log_path.read_text().strip())
        assert record["type"] == "outcome"
        assert record["r_multiple"] == 1.5
        assert record["outcome"] == "tp_hit"

    def test_log_fields_complete(self, tmp_path):
        log_path = tmp_path / "shadow.jsonl"
        sl = ShadowLogger(str(log_path))
        sl.log("2025-06-02T09:00:00Z", "XAU_USD", "buy", 5000.0, 1, 0.85, state_hash="abc123")
        record = json.loads(log_path.read_text().strip())
        assert record["state_hash"] == "abc123"
        assert record["confidence"] == 0.85
        assert record["instrument"] == "XAU_USD"


class TestRLTradeFilter:
    @patch("app.rl.filter.PPO.load")
    def test_assess_returns_action_and_confidence(self, mock_load):
        """assess() returns (int, float) tuple."""
        mock_model = MagicMock()
        mock_model.predict.return_value = (1, None)

        # Mock the probability extraction
        mock_dist = MagicMock()
        mock_dist.distribution.probs = MagicMock()
        import torch
        mock_dist.distribution.probs.cpu.return_value.numpy.return_value = np.array([[0.3, 0.7]])
        mock_model.policy.get_distribution.return_value = mock_dist
        mock_model.policy.obs_to_tensor.return_value = (torch.zeros(1, STATE_DIM),)
        mock_load.return_value = mock_model

        filt = RLTradeFilter("fake_model.zip", confidence_threshold=0.6)
        state = np.zeros(STATE_DIM, dtype=np.float32)
        action, confidence = filt.assess(state)

        assert action in [0, 1]
        assert isinstance(confidence, float)
        assert 0.0 <= confidence <= 1.0

    @patch("app.rl.filter.PPO.load")
    def test_should_take_above_threshold(self, mock_load):
        """should_take returns True when action=TAKE and confidence >= threshold."""
        mock_model = MagicMock()
        mock_model.predict.return_value = (1, None)
        mock_dist = MagicMock()
        import torch
        mock_dist.distribution.probs.cpu.return_value.numpy.return_value = np.array([[0.2, 0.8]])
        mock_model.policy.get_distribution.return_value = mock_dist
        mock_model.policy.obs_to_tensor.return_value = (torch.zeros(1, STATE_DIM),)
        mock_load.return_value = mock_model

        filt = RLTradeFilter("fake_model.zip", confidence_threshold=0.6)
        state = np.zeros(STATE_DIM, dtype=np.float32)
        assert filt.should_take(state) is True

    @patch("app.rl.filter.PPO.load")
    def test_should_take_below_threshold(self, mock_load):
        """should_take returns False when confidence < threshold."""
        mock_model = MagicMock()
        mock_model.predict.return_value = (1, None)
        mock_dist = MagicMock()
        import torch
        mock_dist.distribution.probs.cpu.return_value.numpy.return_value = np.array([[0.45, 0.55]])
        mock_model.policy.get_distribution.return_value = mock_dist
        mock_model.policy.obs_to_tensor.return_value = (torch.zeros(1, STATE_DIM),)
        mock_load.return_value = mock_model

        filt = RLTradeFilter("fake_model.zip", confidence_threshold=0.6)
        state = np.zeros(STATE_DIM, dtype=np.float32)
        assert filt.should_take(state) is False  # 0.55 < 0.6

    @patch("app.rl.filter.PPO.load")
    def test_bad_state_shape_raises(self, mock_load):
        mock_load.return_value = MagicMock()
        filt = RLTradeFilter("fake_model.zip")
        with pytest.raises(ValueError, match="Expected state shape"):
            filt.assess(np.zeros(10, dtype=np.float32))


class TestEngineRLBackwardCompat:
    """Verify engine works without RL filter configured."""

    def test_stream_config_default_no_rl(self):
        from app.models.stream_config import StreamConfig
        cfg = StreamConfig(
            name="test",
            instrument="EUR_USD",
            strategy="sr_rejection",
        )
        assert cfg.rl_filter is None
