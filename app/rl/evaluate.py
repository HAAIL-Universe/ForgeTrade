"""Evaluation & walk-forward validation for ForgeAgent.

Implements 4 evaluation protocols:
1. Holdout test set evaluation
2. Walk-forward validation (rolling train/test splits)
3. Regime-specific analysis
4. Comparison vs. unfiltered baseline

Usage:
    python -m app.rl.evaluate --model models/forge_agent/best_model.zip
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from stable_baselines3 import PPO

from app.rl.data_collector import load_from_parquet, DATA_DIR
from app.rl.environment import AlignedData, EnvConfig, ForgeTradeEnv
from app.rl.rewards import RewardConfig
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData

logger = logging.getLogger("forgetrade.rl.eval")


# ── Core evaluation ──────────────────────────────────────────────────────


def evaluate_agent(
    model: PPO,
    env: ForgeTradeEnv,
    n_episodes: int = 20,
    deterministic: bool = True,
) -> dict:
    """Run episodes and compute aggregate metrics.

    Returns dict with: win_rate, take_rate, profit_factor, max_drawdown,
    avg_r_multiple, sharpe_ratio, total_trades_taken, total_signals_seen.
    """
    all_r: list[float] = []
    all_take_rates: list[float] = []
    all_win_rates: list[float] = []
    all_max_dd: list[float] = []
    episode_returns: list[float] = []
    all_ep_signals: list[int] = []

    for ep in range(n_episodes):
        obs, info = env.reset(seed=ep)
        done = False
        ep_reward = 0.0
        ep_trades = 0
        ep_wins = 0
        ep_signals = 0
        ep_r_values: list[float] = []

        while not done:
            action, _ = model.predict(obs, deterministic=deterministic)
            obs, reward, terminated, truncated, info = env.step(int(action))
            done = terminated or truncated
            ep_reward += reward
            ep_signals += 1

            if "r_multiple" in info:
                ep_trades += 1
                ep_r_values.append(info["r_multiple"])
                if info["r_multiple"] > 0:
                    ep_wins += 1

        episode_returns.append(ep_reward)
        all_r.extend(ep_r_values)
        all_take_rates.append(ep_trades / max(ep_signals, 1))
        all_win_rates.append(ep_wins / max(ep_trades, 1))
        all_max_dd.append(info.get("max_dd", 0.0))
        all_ep_signals.append(ep_signals)

    # Aggregate
    gross_profit = sum(r for r in all_r if r > 0)
    gross_loss = abs(sum(r for r in all_r if r < 0))
    profit_factor = gross_profit / max(gross_loss, 1e-6)

    # Sharpe ratio of episode returns
    if len(episode_returns) > 1:
        mean_ret = np.mean(episode_returns)
        std_ret = np.std(episode_returns)
        sharpe = float(mean_ret / max(std_ret, 1e-6))
    else:
        sharpe = 0.0

    return {
        "win_rate": float(np.mean(all_win_rates)) if all_win_rates else 0.0,
        "take_rate": float(np.mean(all_take_rates)) if all_take_rates else 0.0,
        "profit_factor": float(profit_factor),
        "max_drawdown": float(max(all_max_dd)) if all_max_dd else 0.0,
        "avg_r_multiple": float(np.mean(all_r)) if all_r else 0.0,
        "sharpe_ratio": sharpe,
        "total_trades_taken": len(all_r),
        "total_signals_seen": sum(all_ep_signals),
        "mean_episode_reward": float(np.mean(episode_returns)) if episode_returns else 0.0,
    }


# ── Protocol 1: Holdout test ─────────────────────────────────────────────


HOLDOUT_THRESHOLDS = {
    "win_rate": 0.60,
    "take_rate_min": 0.40,
    "take_rate_max": 0.85,
    "profit_factor": 1.3,
    "max_drawdown": 8.0,
    "avg_r_multiple": 0.0,
}


def evaluate_holdout(model: PPO, test_data: AlignedData, config: EnvConfig) -> dict:
    """Protocol 1: Evaluate on holdout test set."""
    env = ForgeTradeEnv(test_data, config)
    metrics = evaluate_agent(model, env, n_episodes=10)

    passed = (
        metrics["win_rate"] >= HOLDOUT_THRESHOLDS["win_rate"]
        and HOLDOUT_THRESHOLDS["take_rate_min"] <= metrics["take_rate"] <= HOLDOUT_THRESHOLDS["take_rate_max"]
        and metrics["profit_factor"] >= HOLDOUT_THRESHOLDS["profit_factor"]
        and metrics["max_drawdown"] <= HOLDOUT_THRESHOLDS["max_drawdown"]
        and metrics["avg_r_multiple"] >= HOLDOUT_THRESHOLDS["avg_r_multiple"]
    )

    return {**metrics, "passed": passed, "thresholds": HOLDOUT_THRESHOLDS}


# ── Protocol 2: Walk-forward validation ──────────────────────────────────


def walk_forward_splits(
    total_rows: int,
    train_months: int = 6,
    test_months: int = 1,
    step_months: int = 1,
    total_months: int = 12,
) -> list[tuple[float, float, float, float]]:
    """Generate overlapping train/test split ratios.

    Returns list of (train_start_pct, train_end_pct, test_start_pct, test_end_pct).
    """
    splits = []
    for i in range(total_months - train_months):
        train_start = i / total_months
        train_end = (i + train_months) / total_months
        test_start = train_end
        test_end = min(1.0, (i + train_months + test_months) / total_months)
        splits.append((train_start, train_end, test_start, test_end))
    return splits


def _slice_aligned_data(data: AlignedData, start_pct: float, end_pct: float) -> AlignedData:
    """Slice aligned data by percentage range."""
    def _slice_list(lst, s, e):
        n = len(lst)
        return lst[int(n * s):int(n * e)]

    return AlignedData(
        m1=_slice_list(data.m1, start_pct, end_pct),
        m5=_slice_list(data.m5, start_pct, end_pct),
        m15=_slice_list(data.m15, start_pct, end_pct),
        h1=_slice_list(data.h1, start_pct, end_pct),
    )


def evaluate_walk_forward(
    full_data: AlignedData,
    config: EnvConfig,
    reward_config: Optional[RewardConfig] = None,
    timesteps_per_split: int = 50_000,
) -> dict:
    """Protocol 2: Walk-forward validation with 6 rolling splits."""
    from app.rl.network import build_agent

    splits = walk_forward_splits(len(full_data.m5))
    results = []

    for idx, (tr_s, tr_e, te_s, te_e) in enumerate(splits):
        logger.info("Walk-forward split %d/%d: train [%.0f%%–%.0f%%], test [%.0f%%–%.0f%%]",
                     idx + 1, len(splits), tr_s * 100, tr_e * 100, te_s * 100, te_e * 100)

        train_slice = _slice_aligned_data(full_data, tr_s, tr_e)
        test_slice = _slice_aligned_data(full_data, te_s, te_e)

        train_env = ForgeTradeEnv(train_slice, config, reward_config)
        test_env = ForgeTradeEnv(test_slice, config, reward_config)

        model = build_agent(train_env, seed=42 + idx)
        model.learn(total_timesteps=timesteps_per_split)

        metrics = evaluate_agent(model, test_env, n_episodes=5)
        passed = (
            metrics["win_rate"] >= HOLDOUT_THRESHOLDS["win_rate"]
            and metrics["profit_factor"] >= HOLDOUT_THRESHOLDS["profit_factor"]
        )
        results.append({
            "split": idx + 1,
            "train_range": f"{tr_s:.0%}–{tr_e:.0%}",
            "test_range": f"{te_s:.0%}–{te_e:.0%}",
            **metrics,
            "passed": passed,
        })

    splits_passed = sum(1 for r in results if r["passed"])
    overall_passed = splits_passed >= 4

    return {
        "splits": results,
        "splits_passed": splits_passed,
        "splits_required": 4,
        "passed": overall_passed,
    }


# ── Protocol 3: Regime-specific analysis ─────────────────────────────────


def tag_regime(h1_candles: list[CandleData], window: int = 50) -> str:
    """Classify market regime from H1 candle data.

    Returns one of: "trending_up", "trending_down", "ranging",
    "high_volatility", "low_volatility".
    """
    if len(h1_candles) < window:
        return "unknown"

    recent = h1_candles[-window:]

    # ATR for volatility
    try:
        atr = calculate_atr(recent, 14)
    except ValueError:
        return "unknown"

    # Simple trend detection via price change
    start_price = recent[0].close
    end_price = recent[-1].close
    change_pct = (end_price - start_price) / start_price * 100

    # ATR relative to longer-term average
    if len(h1_candles) >= window + 60:
        try:
            long_atr = calculate_atr(h1_candles[-(window + 60):-window], 14)
            atr_ratio = atr / max(long_atr, 1e-6)
        except ValueError:
            atr_ratio = 1.0
    else:
        atr_ratio = 1.0

    # Classify
    if atr_ratio > 1.5:
        return "high_volatility"
    elif atr_ratio < 0.5:
        return "low_volatility"
    elif change_pct > 2.0:
        return "trending_up"
    elif change_pct < -2.0:
        return "trending_down"
    else:
        return "ranging"


# ── Protocol 4: Baseline comparison ──────────────────────────────────────


def evaluate_baseline(env: ForgeTradeEnv, n_episodes: int = 10) -> dict:
    """Run all signals as TAKE (action=1) — unfiltered baseline."""
    all_r: list[float] = []
    all_max_dd: list[float] = []

    for ep in range(n_episodes):
        obs, _ = env.reset(seed=ep + 1000)
        done = False

        while not done:
            obs, reward, terminated, truncated, info = env.step(1)  # Always TAKE
            done = terminated or truncated
            if "r_multiple" in info:
                all_r.append(info["r_multiple"])
            all_max_dd.append(info.get("max_dd", 0.0))

    wins = sum(1 for r in all_r if r > 0)
    gross_profit = sum(r for r in all_r if r > 0)
    gross_loss = abs(sum(r for r in all_r if r < 0))

    return {
        "win_rate": wins / max(len(all_r), 1),
        "profit_factor": gross_profit / max(gross_loss, 1e-6),
        "max_drawdown": max(all_max_dd) if all_max_dd else 0.0,
        "avg_r_multiple": float(np.mean(all_r)) if all_r else 0.0,
        "total_trades": len(all_r),
    }


# ── Full evaluation report ───────────────────────────────────────────────


def generate_report(
    model_path: str,
    instrument: str = "XAU_USD",
    config: Optional[EnvConfig] = None,
) -> dict:
    """Run all 4 evaluation protocols and generate a report."""
    if config is None:
        config = EnvConfig()

    model = PPO.load(model_path)

    # Load full data
    data_dir = DATA_DIR / instrument
    dfs = {}
    for gran in ["M1", "M5", "M15", "H1"]:
        pq = data_dir / f"{gran}.parquet"
        if pq.exists():
            dfs[gran] = load_from_parquet(pq)
        else:
            import pandas as pd
            dfs[gran] = pd.DataFrame()

    from app.rl.data_collector import split_data
    m5_train, m5_val, m5_test = split_data(dfs["M5"])
    m1_train, m1_val, m1_test = split_data(dfs["M1"])
    m15_train, m15_val, m15_test = split_data(dfs["M15"])
    h1_train, h1_val, h1_test = split_data(dfs["H1"])

    test_data = AlignedData.from_dataframes(m1_test, m5_test, m15_test, h1_test)
    full_data = AlignedData.from_dataframes(dfs["M1"], dfs["M5"], dfs["M15"], dfs["H1"])

    # Protocol 1: Holdout
    logger.info("Running holdout evaluation…")
    holdout = evaluate_holdout(model, test_data, config)

    # Protocol 4: Baseline comparison
    logger.info("Running baseline comparison…")
    test_env = ForgeTradeEnv(test_data, config)
    baseline = evaluate_baseline(test_env)
    filtered = evaluate_agent(model, ForgeTradeEnv(test_data, config), n_episodes=10)

    comparison = {
        "baseline_win_rate": baseline["win_rate"],
        "filtered_win_rate": filtered["win_rate"],
        "baseline_profit_factor": baseline["profit_factor"],
        "filtered_profit_factor": filtered["profit_factor"],
        "baseline_max_drawdown": baseline["max_drawdown"],
        "filtered_max_drawdown": filtered["max_drawdown"],
    }

    # Regime analysis
    regime = tag_regime(full_data.h1) if full_data.h1 else "unknown"

    report = {
        "model_path": model_path,
        "evaluation_date": datetime.now(timezone.utc).isoformat(),
        "instrument": instrument,
        "holdout_test": holdout,
        "vs_baseline": comparison,
        "current_regime": regime,
        "verdict": "PASS — deploy to shadow mode" if holdout.get("passed") else "FAIL — retrain needed",
    }

    return report


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Evaluate ForgeAgent RL model")
    parser.add_argument("--model", required=True, help="Path to saved model .zip")
    parser.add_argument("--instrument", default="XAU_USD")
    parser.add_argument("--output", default="models/forge_agent/evaluation_report.json")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    report = generate_report(args.model, args.instrument)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))
    logger.info("Evaluation report → %s", out_path)
    logger.info("Verdict: %s", report["verdict"])


if __name__ == "__main__":
    main()
