"""Tests for app.rl.network — ForgeFeatureExtractor, build_agent, param count."""

import gymnasium as gym
import numpy as np
import pytest
import torch

from app.rl.features import STATE_DIM
from app.rl.network import ForgeFeatureExtractor, PPO_CONFIG, build_agent, count_parameters


class TestForgeFeatureExtractor:
    @pytest.fixture
    def obs_space(self):
        return gym.spaces.Box(low=-3.0, high=3.0, shape=(STATE_DIM,), dtype=np.float32)

    def test_output_shape(self, obs_space):
        extractor = ForgeFeatureExtractor(obs_space, features_dim=64)
        x = torch.randn(1, STATE_DIM)
        out = extractor(x)
        assert out.shape == (1, 64)

    def test_batch_forward(self, obs_space):
        extractor = ForgeFeatureExtractor(obs_space, features_dim=64)
        x = torch.randn(32, STATE_DIM)
        out = extractor(x)
        assert out.shape == (32, 64)

    def test_output_dtype(self, obs_space):
        extractor = ForgeFeatureExtractor(obs_space, features_dim=64)
        x = torch.randn(4, STATE_DIM)
        out = extractor(x)
        assert out.dtype == torch.float32

    def test_gradient_flow(self, obs_space):
        """All layers receive gradients."""
        extractor = ForgeFeatureExtractor(obs_space, features_dim=64)
        x = torch.randn(4, STATE_DIM, requires_grad=False)
        out = extractor(x)
        loss = out.sum()
        loss.backward()
        for name, param in extractor.named_parameters():
            if param.requires_grad:
                assert param.grad is not None, f"No gradient for {name}"
                assert param.grad.abs().sum() > 0, f"Zero gradient for {name}"

    def test_no_nan_output(self, obs_space):
        extractor = ForgeFeatureExtractor(obs_space, features_dim=64)
        extractor.eval()
        x = torch.randn(8, STATE_DIM)
        out = extractor(x)
        assert not torch.isnan(out).any()


class TestBuildAgent:
    @pytest.fixture
    def dummy_env(self):
        """Minimal Gym env matching ForgeTradeEnv spaces."""
        obs_space = gym.spaces.Box(low=-3.0, high=3.0, shape=(STATE_DIM,), dtype=np.float32)
        act_space = gym.spaces.Discrete(2)

        class _StubEnv(gym.Env):
            observation_space = obs_space
            action_space = act_space

            def reset(self, **kwargs):
                return np.zeros(STATE_DIM, dtype=np.float32), {}

            def step(self, action):
                return np.zeros(STATE_DIM, dtype=np.float32), 0.0, True, False, {}

        return _StubEnv()

    def test_returns_ppo(self, dummy_env):
        from stable_baselines3 import PPO
        model = build_agent(dummy_env)
        assert isinstance(model, PPO)

    def test_parameter_count(self, dummy_env):
        model = build_agent(dummy_env)
        n_params = count_parameters(model)
        # Phase 13 spec: ~20K params
        assert 10_000 < n_params < 40_000, f"Expected ~20K params, got {n_params}"

    def test_predict_shape(self, dummy_env):
        model = build_agent(dummy_env)
        obs = np.zeros(STATE_DIM, dtype=np.float32)
        action, _states = model.predict(obs, deterministic=True)
        assert action in [0, 1]

    def test_custom_seed(self, dummy_env):
        model = build_agent(dummy_env, seed=123)
        assert model.seed == 123


class TestPPOConfig:
    def test_learning_rate(self):
        assert PPO_CONFIG["learning_rate"] == 3e-4

    def test_clip_range(self):
        assert PPO_CONFIG["clip_range"] == 0.2

    def test_entropy_coef(self):
        assert PPO_CONFIG["ent_coef"] == 0.01
