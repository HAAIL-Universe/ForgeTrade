"""Neural network architecture for ForgeAgent.

Custom 3-layer shared feature extractor + dual head (policy + value)
for PPO, integrated via Stable Baselines 3.
"""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import torch
import torch.nn as nn
from stable_baselines3 import PPO
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

from app.rl.features import STATE_DIM


# ── Custom feature extractor ─────────────────────────────────────────────


class ForgeFeatureExtractor(BaseFeaturesExtractor):
    """3-layer shared encoder: 27 → 128 → 64 → 64 with LayerNorm + LeakyReLU.

    ~20K parameters total.  Small enough to avoid overfitting on 12 months
    of Gold data, expressive enough for pairwise and 3-way feature interactions.
    """

    def __init__(
        self,
        observation_space: gym.spaces.Box,
        features_dim: int = 64,
    ) -> None:
        super().__init__(observation_space, features_dim)

        in_dim = observation_space.shape[0]  # 27

        self.net = nn.Sequential(
            nn.Linear(in_dim, 128),
            nn.LayerNorm(128),
            nn.LeakyReLU(0.01),
            nn.Dropout(0.1),

            nn.Linear(128, 64),
            nn.LayerNorm(64),
            nn.LeakyReLU(0.01),
            nn.Dropout(0.1),

            nn.Linear(64, 64),
            nn.LayerNorm(64),
            nn.LeakyReLU(0.01),
        )

    def forward(self, observations: torch.Tensor) -> torch.Tensor:
        return self.net(observations)


# ── PPO hyperparameters ──────────────────────────────────────────────────

PPO_CONFIG: dict[str, Any] = {
    "learning_rate": 3e-4,
    "n_steps": 2048,
    "batch_size": 64,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.95,
    "clip_range": 0.2,
    "ent_coef": 0.01,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "seed": 42,
}


def build_agent(
    env: gym.Env,
    *,
    total_timesteps: int = 500_000,
    tensorboard_log: str | None = None,
    seed: int = 42,
) -> PPO:
    """Build a PPO agent with the ForgeFeatureExtractor.

    Args:
        env: Gymnasium environment (ForgeTradeEnv).
        total_timesteps: Ignored here (used in .learn()), but stored
            for reference via the returned model.
        tensorboard_log: Path for TensorBoard logs (or None).
        seed: Random seed.

    Returns:
        Configured ``PPO`` instance ready for ``.learn()``.
    """
    policy_kwargs = {
        "features_extractor_class": ForgeFeatureExtractor,
        "features_extractor_kwargs": {"features_dim": 64},
        "net_arch": {"pi": [32], "vf": [32]},
        "activation_fn": nn.LeakyReLU,
        "share_features_extractor": True,
    }

    model = PPO(
        policy="MlpPolicy",
        env=env,
        learning_rate=PPO_CONFIG["learning_rate"],
        n_steps=PPO_CONFIG["n_steps"],
        batch_size=PPO_CONFIG["batch_size"],
        n_epochs=PPO_CONFIG["n_epochs"],
        gamma=PPO_CONFIG["gamma"],
        gae_lambda=PPO_CONFIG["gae_lambda"],
        clip_range=PPO_CONFIG["clip_range"],
        ent_coef=PPO_CONFIG["ent_coef"],
        vf_coef=PPO_CONFIG["vf_coef"],
        max_grad_norm=PPO_CONFIG["max_grad_norm"],
        tensorboard_log=tensorboard_log,
        policy_kwargs=policy_kwargs,
        seed=seed,
        verbose=0,
    )

    return model


def count_parameters(model: PPO) -> int:
    """Count total trainable parameters in the PPO model."""
    return sum(p.numel() for p in model.policy.parameters() if p.requires_grad)
