"""Training pipeline for ForgeAgent.

Orchestrates: load data → create envs → train PPO → validate →
save checkpoints → log metrics.

Usage:
    python -m app.rl.train --instrument XAU_USD --timesteps 500000
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Optional

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, EvalCallback

from app.rl.data_collector import load_from_parquet, split_data, DATA_DIR
from app.rl.environment import AlignedData, EnvConfig, ForgeTradeEnv, NoisyObservationWrapper
from app.rl.network import build_agent, count_parameters
from app.rl.rewards import RewardConfig

logger = logging.getLogger("forgetrade.rl.train")

MODELS_DIR = Path("models") / "forge_agent"


# ── Custom training callback ─────────────────────────────────────────────


class ForgeTrainingCallback(BaseCallback):
    """Logs trading-specific metrics to TensorBoard."""

    def __init__(self, verbose: int = 0):
        super().__init__(verbose)
        self._episode_takes = 0
        self._episode_wins = 0
        self._episode_signals = 0

    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [])
        for info in infos:
            if "take_rate" in info:
                self.logger.record("forge/take_rate", info["take_rate"])
            if "win_rate" in info:
                self.logger.record("forge/win_rate", info["win_rate"])
            if "avg_r" in info:
                self.logger.record("forge/avg_r_multiple", info["avg_r"])
            if "max_dd" in info:
                self.logger.record("forge/max_drawdown", info["max_dd"])
        return True


# ── Data loading ─────────────────────────────────────────────────────────


def load_training_data(
    instrument: str,
    train_pct: float = 0.70,
    val_pct: float = 0.15,
) -> tuple[AlignedData, AlignedData, AlignedData]:
    """Load parquet data and split into train/val/test AlignedData."""
    data_dir = DATA_DIR / instrument

    dfs = {}
    for gran in ["M1", "M5", "M15", "H1"]:
        pq_path = data_dir / f"{gran}.parquet"
        if pq_path.exists():
            dfs[gran] = load_from_parquet(pq_path)
        else:
            import pandas as pd
            dfs[gran] = pd.DataFrame()

    # Split each timeframe chronologically using the same ratios
    splits = {}
    for gran in ["M1", "M5", "M15", "H1"]:
        tr, va, te = split_data(dfs[gran], train_pct, val_pct)
        splits[gran] = (tr, va, te)

    train_data = AlignedData.from_dataframes(
        m1_df=splits["M1"][0],
        m5_df=splits["M5"][0],
        m15_df=splits["M15"][0],
        h1_df=splits["H1"][0],
    )
    val_data = AlignedData.from_dataframes(
        m1_df=splits["M1"][1],
        m5_df=splits["M5"][1],
        m15_df=splits["M15"][1],
        h1_df=splits["H1"][1],
    )
    test_data = AlignedData.from_dataframes(
        m1_df=splits["M1"][2],
        m5_df=splits["M5"][2],
        m15_df=splits["M15"][2],
        h1_df=splits["H1"][2],
    )

    return train_data, val_data, test_data


# ── Training function ────────────────────────────────────────────────────


def train(
    instrument: str = "XAU_USD",
    total_timesteps: int = 500_000,
    env_config: Optional[EnvConfig] = None,
    reward_config: Optional[RewardConfig] = None,
    noise_std: float = 0.02,
    seed: int = 42,
) -> Path:
    """Run the full training pipeline.

    Returns path to the saved best model.
    """
    if env_config is None:
        env_config = EnvConfig()
    if reward_config is None:
        reward_config = RewardConfig()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    tb_log_dir = str(MODELS_DIR / "tensorboard")

    # 1 ── Load data
    logger.info("Loading training data for %s…", instrument)
    train_data, val_data, _test_data = load_training_data(instrument)

    logger.info(
        "Data loaded. Train: %d M5, %d M1  |  Val: %d M5, %d M1",
        len(train_data.m5), len(train_data.m1),
        len(val_data.m5), len(val_data.m1),
    )

    # 2 ── Create environments
    train_env = ForgeTradeEnv(train_data, env_config, reward_config)
    train_env = NoisyObservationWrapper(train_env, noise_std=noise_std)

    val_env = ForgeTradeEnv(val_data, env_config, reward_config)

    # 3 ── Build agent
    logger.info("Building PPO agent…")
    model = build_agent(
        train_env,
        total_timesteps=total_timesteps,
        tensorboard_log=tb_log_dir,
        seed=seed,
    )
    param_count = count_parameters(model)
    logger.info("Agent built. Parameters: %d", param_count)

    # 4 ── Callbacks
    eval_callback = EvalCallback(
        val_env,
        best_model_save_path=str(MODELS_DIR),
        log_path=str(MODELS_DIR),
        eval_freq=max(2048 * 10, 1),  # Every 10 rollouts
        n_eval_episodes=5,
        deterministic=True,
        verbose=0,
    )

    forge_callback = ForgeTrainingCallback()

    # 5 ── Train
    logger.info("Starting training for %d timesteps…", total_timesteps)
    model.learn(
        total_timesteps=total_timesteps,
        callback=[eval_callback, forge_callback],
        progress_bar=False,
    )

    # 6 ── Save final model
    final_path = MODELS_DIR / "final_model"
    model.save(str(final_path))
    logger.info("Final model saved → %s", final_path)

    # Best model saved by EvalCallback as "best_model.zip"
    best_path = MODELS_DIR / "best_model.zip"

    # 7 ── Training report
    report = {
        "instrument": instrument,
        "total_timesteps": total_timesteps,
        "parameters": param_count,
        "seed": seed,
        "env_config": asdict(env_config),
        "reward_config": asdict(reward_config),
        "model_paths": {
            "best": str(best_path),
            "final": str(final_path),
        },
    }
    report_path = MODELS_DIR / "training_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Training report → %s", report_path)

    return best_path


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Train ForgeAgent RL model")
    parser.add_argument("--instrument", default="XAU_USD")
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--noise", type=float, default=0.02)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    train(
        instrument=args.instrument,
        total_timesteps=args.timesteps,
        seed=args.seed,
        noise_std=args.noise,
    )


if __name__ == "__main__":
    main()
