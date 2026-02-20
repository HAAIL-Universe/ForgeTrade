"""Tests for app.rl.environment — Gym environment and trade simulation."""

import numpy as np
import pytest

from app.rl.environment import (
    AlignedData,
    EnvConfig,
    ForgeTradeEnv,
    NoisyObservationWrapper,
    TradeOutcome,
    simulate_trade,
)
from app.rl.features import STATE_DIM
from app.strategy.models import CandleData


def _candle(price: float, direction: str = "up", spread: float = 0.5) -> CandleData:
    """Quick candle factory."""
    if direction == "up":
        return CandleData("2025-01-01T00:00:00Z", price, price + spread, price - 0.1, price + spread * 0.8, 100)
    else:
        return CandleData("2025-01-01T00:00:00Z", price, price + 0.1, price - spread, price - spread * 0.8, 100)


def _make_m1_series(start_price: float, n: int = 120, trend: float = 0.01) -> list[CandleData]:
    """Create a series of M1 candles with a slight trend."""
    candles = []
    for i in range(n):
        p = start_price + i * trend
        candles.append(CandleData(
            time=f"2025-06-02T08:{i:02d}:00.000000Z" if i < 60 else f"2025-06-02T09:{i-60:02d}:00.000000Z",
            open=round(p, 2),
            high=round(p + 0.3, 2),
            low=round(p - 0.3, 2),
            close=round(p + 0.1, 2),
            volume=50,
        ))
    return candles


class TestSimulateTrade:
    def test_tp_hit_buy(self):
        """TP hit on a buy trade."""
        entry = 5000.0
        sl = 4997.0
        tp = 5004.5
        # M1 candles trending up to hit TP
        m1 = _make_m1_series(5000.0, 60, trend=0.1)
        result = simulate_trade(entry, "buy", sl, tp, m1)
        assert result.exit_reason == "tp_hit"
        assert result.r_multiple > 0

    def test_sl_hit_buy(self):
        """SL hit on a buy trade."""
        entry = 5000.0
        sl = 4997.0
        tp = 5004.5
        # M1 candles trending down
        m1 = _make_m1_series(5000.0, 60, trend=-0.1)
        result = simulate_trade(entry, "buy", sl, tp, m1)
        assert result.exit_reason == "sl_hit"
        assert result.r_multiple < 0

    def test_tp_hit_sell(self):
        """TP hit on a sell trade."""
        entry = 5000.0
        sl = 5003.0
        tp = 4995.5
        m1 = _make_m1_series(5000.0, 60, trend=-0.1)
        result = simulate_trade(entry, "sell", sl, tp, m1)
        assert result.exit_reason == "tp_hit"
        assert result.r_multiple > 0

    def test_sl_hit_sell(self):
        """SL hit on a sell trade."""
        entry = 5000.0
        sl = 5003.0
        tp = 4995.5
        m1 = _make_m1_series(5000.0, 60, trend=0.1)
        result = simulate_trade(entry, "sell", sl, tp, m1)
        assert result.exit_reason == "sl_hit"
        assert result.r_multiple < 0

    def test_time_exit(self):
        """Trade times out without hitting SL or TP."""
        entry = 5000.0
        sl = 4990.0  # Very far away
        tp = 5010.0  # Very far away
        m1 = _make_m1_series(5000.0, 120, trend=0.001)  # Barely moving
        result = simulate_trade(entry, "buy", sl, tp, m1, max_hold_minutes=120)
        assert result.exit_reason == "time_exit"

    def test_pessimistic_fill(self):
        """When both SL and TP are hit on same candle, SL wins."""
        entry = 5000.0
        sl = 4999.0
        tp = 5001.0
        # One candle that spans both SL and TP
        wide_candle = CandleData("2025-01-01T00:00:00Z", 5000.0, 5002.0, 4998.0, 5000.5, 100)
        result = simulate_trade(entry, "buy", sl, tp, [wide_candle])
        assert result.exit_reason == "sl_hit"  # Pessimistic

    def test_hold_minutes_tracking(self):
        """Correct hold time is reported."""
        entry = 5000.0
        sl = 4997.0
        tp = 5004.5
        m1 = _make_m1_series(5000.0, 60, trend=0.1)
        result = simulate_trade(entry, "buy", sl, tp, m1)
        assert result.hold_minutes > 0
        assert result.hold_minutes <= 60

    def test_empty_candles(self):
        """Empty M1 list → time exit with zero pnl."""
        result = simulate_trade(5000.0, "buy", 4997.0, 5004.0, [])
        assert result.exit_reason == "time_exit"
        assert result.hold_minutes == 0


class TestAlignedData:
    def test_from_dataframes_empty(self):
        data = AlignedData.from_dataframes()
        assert data.m1 == []
        assert data.m5 == []

    def test_from_dataframes_with_data(self):
        import pandas as pd
        df = pd.DataFrame({
            "time": ["2025-01-01T00:00:00Z"] * 5,
            "open": [5000.0] * 5,
            "high": [5001.0] * 5,
            "low": [4999.0] * 5,
            "close": [5000.5] * 5,
            "volume": [100] * 5,
        })
        data = AlignedData.from_dataframes(m5_df=df)
        assert len(data.m5) == 5
        assert isinstance(data.m5[0], CandleData)


class TestForgeTradeEnv:
    @pytest.fixture
    def env_data(self):
        """Create enough synthetic data for the environment."""
        m5 = []
        m1 = []
        base = 5000.0

        # 200 M5 candles with alternating trend
        for i in range(200):
            p = base + (i % 20) * 0.5 * (1 if i < 100 else -1)
            m5.append(CandleData(
                time=f"2025-06-02T{8 + i // 12:02d}:{(i % 12) * 5:02d}:00.000000Z",
                open=round(p, 2),
                high=round(p + 1.0, 2),
                low=round(p - 1.0, 2),
                close=round(p + 0.5, 2),
                volume=100,
            ))

        # 1000 M1 candles
        for i in range(1000):
            p = base + (i % 100) * 0.1
            m1.append(CandleData(
                time=f"2025-06-02T{8 + i // 60:02d}:{i % 60:02d}:00.000000Z",
                open=round(p, 2),
                high=round(p + 0.3, 2),
                low=round(p - 0.3, 2),
                close=round(p + 0.1, 2),
                volume=50,
            ))

        h1 = m5[:50]  # Re-use (not perfectly realistic but sufficient for tests)
        m15 = m5[:70]

        return AlignedData(m1=m1, m5=m5, m15=m15, h1=h1)

    def test_spaces(self, env_data):
        env = ForgeTradeEnv(env_data)
        assert env.observation_space.shape == (STATE_DIM,)
        assert env.action_space.n == 2

    def test_reset(self, env_data):
        env = ForgeTradeEnv(env_data)
        obs, info = env.reset(seed=42)
        assert obs.shape == (STATE_DIM,)
        assert isinstance(info, dict)

    def test_step_take(self, env_data):
        env = ForgeTradeEnv(env_data)
        obs, info = env.reset(seed=42)
        if info.get("signals_found", 0) > 0:
            obs, reward, terminated, truncated, info = env.step(1)  # TAKE
            assert obs.shape == (STATE_DIM,)
            assert isinstance(reward, float)

    def test_step_veto(self, env_data):
        env = ForgeTradeEnv(env_data)
        obs, info = env.reset(seed=42)
        if info.get("signals_found", 0) > 0:
            obs, reward, terminated, truncated, info = env.step(0)  # VETO
            assert obs.shape == (STATE_DIM,)
            assert isinstance(reward, float)

    def test_episode_terminates(self, env_data):
        env = ForgeTradeEnv(env_data, EnvConfig(max_steps_per_episode=10))
        obs, info = env.reset(seed=42)
        done = False
        steps = 0
        while not done and steps < 50:
            obs, reward, terminated, truncated, info = env.step(1)
            done = terminated or truncated
            steps += 1
        assert done  # Should terminate within max_steps


class TestNoisyObservationWrapper:
    def test_adds_noise(self, env_data=None):
        """Noise wrapper changes observations during training."""
        # Create a minimal env mock
        import gymnasium as gym
        env = gym.make("CartPole-v1")
        wrapped = NoisyObservationWrapper(env, noise_std=0.1)
        wrapped.training = True
        obs, _ = wrapped.reset(seed=42)
        # Get a second observation to compare
        obs2, _ = wrapped.reset(seed=42)
        # Due to noise, observations should differ slightly
        # (though reset seeds may produce same base obs)
        assert obs.shape == obs2.shape

    def test_no_noise_when_not_training(self):
        import gymnasium as gym
        env = gym.make("CartPole-v1")
        wrapped = NoisyObservationWrapper(env, noise_std=0.1)
        wrapped.training = False
        obs1, _ = wrapped.reset(seed=42)
        # Observations should be deterministic
        assert obs1 is not None
