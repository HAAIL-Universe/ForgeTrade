"""Evaluate ForgeAgent and append results to persistent training tracker.

Usage:
    python -m scripts.eval_agent
    python -m scripts.eval_agent --model models/forge_agent/best_model.zip
    python -m scripts.eval_agent --episodes 30 --label "after strategy tweak v2"

Each run appends a timestamped entry to ``data/agent_training_tracker.json``
with full evaluation metrics + failure analysis so you can track progress.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
from stable_baselines3 import PPO

from app.rl.data_collector import load_from_parquet, split_data, split_data_by_date, DATA_DIR
from app.rl.environment import (
    AlignedData, EnvConfig, ForgeTradeEnv, simulate_trade,
)
from app.rl.evaluate import evaluate_agent
from app.rl.features import ForgeStateBuilder, AccountSnapshot
from app.rl.network import count_parameters
from app.rl.rewards import AccountState, RewardConfig
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData

logger = logging.getLogger("forgetrade.eval_tracker")

TRACKER_PATH = Path("data") / "agent_training_tracker.json"
MODELS_DIR = Path("models") / "forge_agent"


def load_tracker() -> list[dict]:
    """Load existing tracker entries."""
    if TRACKER_PATH.exists():
        return json.loads(TRACKER_PATH.read_text())
    return []


def save_tracker(entries: list[dict]) -> None:
    """Save tracker entries."""
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_PATH.write_text(json.dumps(entries, indent=2, default=str))


# ── Failure analysis ─────────────────────────────────────────────────────


def analyze_failures(
    model: PPO,
    env: ForgeTradeEnv,
    n_episodes: int = 10,
) -> dict:
    """Run episodes recording detailed per-trade failure data.

    Returns a failure analysis dict with breakdowns by:
    - exit_reason (sl_hit, tp_hit, time_exit)
    - hour_of_day
    - volatility regime (low/mid/high ATR)
    - trend_alignment (aligned / counter / neutral)
    - hold_duration buckets
    """
    trades: list[dict] = []
    state_builder = ForgeStateBuilder()

    for ep in range(n_episodes):
        obs, info = env.reset(seed=ep)
        done = False
        step_idx = 0

        while not done:
            action, _ = model.predict(obs, deterministic=True)
            action = int(action)

            # Capture signal data before stepping
            sig = None
            if env._signal_idx < len(env._signals):
                sig = env._signals[env._signal_idx]

            obs, reward, terminated, truncated, info = env.step(action)
            done = terminated or truncated

            if action == 1 and sig is not None:
                # This was a TAKE — record trade details
                entry = {
                    "action": "TAKE",
                    "direction": sig["direction"],
                    "entry_price": sig["entry_price"],
                    "sl": sig["sl"],
                    "tp": sig["tp"],
                    "exit_reason": info.get("trade_result", "unknown"),
                    "r_multiple": info.get("r_multiple", 0.0),
                    "hold_minutes": info.get("hold_minutes", 0),
                    "spread_pips": sig.get("spread_pips", 0.0),
                    "won": info.get("r_multiple", 0.0) > 0,
                }

                # Extract feature context from the signal
                m5_ctx = sig.get("m5_context", [])
                if m5_ctx and hasattr(m5_ctx[-1], "time"):
                    ts = m5_ctx[-1].time
                    try:
                        if isinstance(ts, str):
                            for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                                        "%Y-%m-%dT%H:%M:%S.%f+00:00", "%Y-%m-%dT%H:%M:%S+00:00"):
                                try:
                                    dt = datetime.strptime(ts, fmt)
                                    break
                                except ValueError:
                                    dt = None
                            if dt:
                                entry["hour"] = dt.hour
                                entry["day_of_week"] = dt.weekday()
                        else:
                            entry["hour"] = ts.hour
                            entry["day_of_week"] = ts.weekday()
                    except Exception:
                        pass

                # ATR for volatility regime
                if len(m5_ctx) >= 15:
                    try:
                        atr = calculate_atr(m5_ctx, 14)
                        atr_pips = atr / env.config.pip_value
                        entry["atr_pips"] = round(atr_pips, 1)
                    except (ValueError, IndexError):
                        pass

                # H1 trend for alignment check
                h1_ctx = sig.get("h1_context", [])
                if h1_ctx:
                    try:
                        from app.strategy.indicators import calculate_ema
                        h1_ema21 = calculate_ema(h1_ctx, min(21, len(h1_ctx)))
                        h1_ema50 = calculate_ema(h1_ctx, min(50, len(h1_ctx)))
                        if h1_ema21 and h1_ema50 and not math.isnan(h1_ema21[-1]) and not math.isnan(h1_ema50[-1]):
                            h1_bullish = h1_ema21[-1] > h1_ema50[-1]
                            if sig["direction"] == "buy" and h1_bullish:
                                entry["trend_alignment"] = "aligned"
                            elif sig["direction"] == "sell" and not h1_bullish:
                                entry["trend_alignment"] = "aligned"
                            else:
                                entry["trend_alignment"] = "counter"
                        else:
                            entry["trend_alignment"] = "neutral"
                    except Exception:
                        entry["trend_alignment"] = "neutral"

                trades.append(entry)

            elif action == 0 and sig is not None:
                # VETO — record what would have happened
                trades.append({
                    "action": "VETO",
                    "direction": sig["direction"],
                    "entry_price": sig["entry_price"],
                    "won": False,  # Not applicable
                })

            step_idx += 1

    # ── Build failure analysis ──
    taken = [t for t in trades if t["action"] == "TAKE"]
    losses = [t for t in taken if not t["won"]]
    wins = [t for t in taken if t["won"]]
    vetos = [t for t in trades if t["action"] == "VETO"]

    analysis: dict = {
        "total_signals": len(trades),
        "total_taken": len(taken),
        "total_vetoed": len(vetos),
        "total_wins": len(wins),
        "total_losses": len(losses),
    }

    if not losses:
        analysis["failure_clusters"] = []
        return analysis

    # 1) Exit reason breakdown
    exit_reasons: dict[str, int] = {}
    for t in losses:
        reason = t.get("exit_reason", "unknown")
        exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
    analysis["exit_reasons"] = exit_reasons

    # 2) Hour-of-day breakdown (losses only)
    hour_losses: dict[int, int] = {}
    hour_total: dict[int, int] = {}
    for t in taken:
        h = t.get("hour")
        if h is not None:
            hour_total[h] = hour_total.get(h, 0) + 1
            if not t["won"]:
                hour_losses[h] = hour_losses.get(h, 0) + 1

    worst_hours: list[dict] = []
    for h in sorted(hour_losses, key=lambda x: hour_losses[x], reverse=True):
        total_h = hour_total.get(h, 1)
        loss_rate = hour_losses[h] / total_h
        worst_hours.append({
            "hour": h,
            "losses": hour_losses[h],
            "total": total_h,
            "loss_rate": round(loss_rate, 3),
        })
    analysis["worst_hours"] = worst_hours[:5]

    # 3) Volatility regime
    low_vol_losses = sum(1 for t in losses if t.get("atr_pips", 999) < 120)
    mid_vol_losses = sum(1 for t in losses if 120 <= t.get("atr_pips", 0) < 250)
    high_vol_losses = sum(1 for t in losses if t.get("atr_pips", 0) >= 250)
    low_vol_total = sum(1 for t in taken if t.get("atr_pips", 999) < 120)
    mid_vol_total = sum(1 for t in taken if 120 <= t.get("atr_pips", 0) < 250)
    high_vol_total = sum(1 for t in taken if t.get("atr_pips", 0) >= 250)

    analysis["volatility"] = {
        "low": {"losses": low_vol_losses, "total": low_vol_total,
                "loss_rate": round(low_vol_losses / max(low_vol_total, 1), 3)},
        "mid": {"losses": mid_vol_losses, "total": mid_vol_total,
                "loss_rate": round(mid_vol_losses / max(mid_vol_total, 1), 3)},
        "high": {"losses": high_vol_losses, "total": high_vol_total,
                 "loss_rate": round(high_vol_losses / max(high_vol_total, 1), 3)},
    }

    # 4) Trend alignment
    aligned_losses = sum(1 for t in losses if t.get("trend_alignment") == "aligned")
    counter_losses = sum(1 for t in losses if t.get("trend_alignment") == "counter")
    aligned_total = sum(1 for t in taken if t.get("trend_alignment") == "aligned")
    counter_total = sum(1 for t in taken if t.get("trend_alignment") == "counter")

    analysis["trend_alignment"] = {
        "aligned": {"losses": aligned_losses, "total": aligned_total,
                    "loss_rate": round(aligned_losses / max(aligned_total, 1), 3)},
        "counter": {"losses": counter_losses, "total": counter_total,
                    "loss_rate": round(counter_losses / max(counter_total, 1), 3)},
    }

    # 5) Hold duration
    fast_sl = sum(1 for t in losses if t.get("hold_minutes", 999) < 5)
    short_sl = sum(1 for t in losses if 5 <= t.get("hold_minutes", 0) < 15)
    mid_sl = sum(1 for t in losses if 15 <= t.get("hold_minutes", 0) < 30)
    long_sl = sum(1 for t in losses if t.get("hold_minutes", 0) >= 30)

    analysis["hold_duration"] = {
        "very_fast_0_5min": fast_sl,
        "short_5_15min": short_sl,
        "mid_15_30min": mid_sl,
        "long_30plus_min": long_sl,
    }

    # 6) Direction breakdown
    buy_losses = sum(1 for t in losses if t["direction"] == "buy")
    sell_losses = sum(1 for t in losses if t["direction"] == "sell")
    buy_total = sum(1 for t in taken if t["direction"] == "buy")
    sell_total = sum(1 for t in taken if t["direction"] == "sell")

    analysis["direction"] = {
        "buy": {"losses": buy_losses, "total": buy_total,
                "loss_rate": round(buy_losses / max(buy_total, 1), 3)},
        "sell": {"losses": sell_losses, "total": sell_total,
                 "loss_rate": round(sell_losses / max(sell_total, 1), 3)},
    }

    # 7) Spread at entry
    high_spread_losses = sum(1 for t in losses if t.get("spread_pips", 0) > 4.0)
    high_spread_total = sum(1 for t in taken if t.get("spread_pips", 0) > 4.0)
    analysis["high_spread"] = {
        "losses": high_spread_losses,
        "total": high_spread_total,
        "loss_rate": round(high_spread_losses / max(high_spread_total, 1), 3),
    }

    # 8) Top failure clusters (ranked by impact)
    clusters: list[dict] = []

    # Low vol cluster
    if low_vol_total > 0 and low_vol_losses / max(low_vol_total, 1) > 0.6:
        clusters.append({
            "pattern": "low_volatility",
            "description": f"Low ATR (<120 pips): {low_vol_losses}/{low_vol_total} losses ({low_vol_losses/max(low_vol_total,1):.0%})",
            "impact": low_vol_losses,
            "suggestion": "raise min_atr_pips",
        })

    # Counter-trend cluster
    if counter_total > 0 and counter_losses / max(counter_total, 1) > 0.6:
        clusters.append({
            "pattern": "counter_trend",
            "description": f"Counter-H1-trend: {counter_losses}/{counter_total} losses ({counter_losses/max(counter_total,1):.0%})",
            "impact": counter_losses,
            "suggestion": "require_h1_alignment",
        })

    # High spread cluster
    if high_spread_total > 0 and high_spread_losses / max(high_spread_total, 1) > 0.6:
        clusters.append({
            "pattern": "high_spread",
            "description": f"Spread >4 pips: {high_spread_losses}/{high_spread_total} losses ({high_spread_losses/max(high_spread_total,1):.0%})",
            "impact": high_spread_losses,
            "suggestion": "lower max_spread_pips",
        })

    # Fast SL cluster
    if fast_sl > len(losses) * 0.3:
        clusters.append({
            "pattern": "fast_sl_hit",
            "description": f"SL hit <5min: {fast_sl}/{len(losses)} losses ({fast_sl/len(losses):.0%})",
            "impact": fast_sl,
            "suggestion": "widen sl_buffer_pips",
        })

    # Time exits cluster
    time_exits = exit_reasons.get("time_exit", 0)
    if time_exits > len(losses) * 0.3:
        clusters.append({
            "pattern": "time_exits",
            "description": f"Time exits: {time_exits}/{len(losses)} losses ({time_exits/len(losses):.0%})",
            "impact": time_exits,
            "suggestion": "reduce max_hold_minutes or tighten entry",
        })

    # Worst hours cluster
    if worst_hours and worst_hours[0]["loss_rate"] > 0.7 and worst_hours[0]["total"] >= 5:
        h = worst_hours[0]
        clusters.append({
            "pattern": "bad_session_hour",
            "description": f"Hour {h['hour']}:00 UTC: {h['losses']}/{h['total']} losses ({h['loss_rate']:.0%})",
            "impact": h["losses"],
            "suggestion": "narrow session_window",
        })

    clusters.sort(key=lambda c: c["impact"], reverse=True)
    analysis["failure_clusters"] = clusters[:5]

    return analysis


def run_evaluation(
    model_path: str = "models/forge_agent/best_model.zip",
    instrument: str = "XAU_USD",
    n_episodes: int = 20,
    label: str = "",
    include_failures: bool = True,
    env_config: EnvConfig | None = None,
    reward_config: RewardConfig | None = None,
) -> dict:
    """Run evaluation and return the metrics dict."""
    # Load model
    model = PPO.load(model_path)
    param_count = count_parameters(model)

    # Load test data (last 15% of historical data)
    data_dir = DATA_DIR / instrument
    dfs = {}
    for gran in ["M1", "M5", "M15", "H1"]:
        pq_path = data_dir / f"{gran}.parquet"
        if pq_path.exists():
            dfs[gran] = load_from_parquet(pq_path)
        else:
            import pandas as pd
            dfs[gran] = pd.DataFrame()

    # Split: 70/15/15 by M5 date boundaries — use test set
    splits = split_data_by_date(dfs, reference_gran="M5", train_pct=0.70, val_pct=0.15)

    test_data = AlignedData.from_dataframes(
        m1_df=splits["M1"][2],
        m5_df=splits["M5"][2],
        m15_df=splits["M15"][2],
        h1_df=splits["H1"][2],
    )

    # Run evaluation
    config = env_config or EnvConfig(instrument=instrument)
    reward_cfg = reward_config or RewardConfig()
    env = ForgeTradeEnv(test_data, config, reward_cfg)

    metrics = evaluate_agent(model, env, n_episodes=n_episodes, deterministic=True)

    # Run failure analysis
    failure_analysis = None
    if include_failures:
        env2 = ForgeTradeEnv(test_data, config, reward_cfg)
        failure_analysis = analyze_failures(model, env2, n_episodes=min(n_episodes, 10))

    # Also load training report if it exists for context
    report_path = MODELS_DIR / "training_report.json"
    training_timesteps = None
    if report_path.exists():
        report = json.loads(report_path.read_text())
        training_timesteps = report.get("total_timesteps")

    # Build tracker entry
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "label": label or f"eval-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}",
        "model_path": model_path,
        "instrument": instrument,
        "parameters": param_count,
        "training_timesteps": training_timesteps,
        "eval_episodes": n_episodes,
        "metrics": {
            "win_rate": round(metrics["win_rate"], 4),
            "take_rate": round(metrics["take_rate"], 4),
            "profit_factor": round(metrics["profit_factor"], 4),
            "max_drawdown": round(metrics["max_drawdown"], 4),
            "avg_r_multiple": round(metrics["avg_r_multiple"], 4),
            "sharpe_ratio": round(metrics["sharpe_ratio"], 4),
            "mean_episode_reward": round(metrics["mean_episode_reward"], 4),
            "total_trades_taken": metrics["total_trades_taken"],
            "total_signals_seen": metrics["total_signals_seen"],
        },
    }

    if failure_analysis:
        entry["failures"] = failure_analysis

    return entry


def main():
    parser = argparse.ArgumentParser(description="Evaluate ForgeAgent and track progress")
    parser.add_argument("--model", default="models/forge_agent/best_model.zip")
    parser.add_argument("--instrument", default="XAU_USD")
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--label", default="", help="Label for this evaluation run")
    parser.add_argument("--no-failures", action="store_true", help="Skip failure analysis")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info("Running evaluation: %s (%d episodes)…", args.model, args.episodes)
    entry = run_evaluation(
        model_path=args.model,
        instrument=args.instrument,
        n_episodes=args.episodes,
        label=args.label,
        include_failures=not args.no_failures,
    )

    # Append to tracker
    tracker = load_tracker()
    tracker.append(entry)
    save_tracker(tracker)

    # Print results
    m = entry["metrics"]
    print("\n" + "=" * 60)
    print(f"  ForgeAgent Evaluation — {entry['label']}")
    print("=" * 60)
    print(f"  Model:          {entry['model_path']}")
    print(f"  Parameters:     {entry['parameters']:,}")
    print(f"  Trained:        {entry['training_timesteps']:,} timesteps" if entry['training_timesteps'] else "  Trained:        unknown")
    print(f"  Eval episodes:  {entry['eval_episodes']}")
    print()
    print(f"  Win Rate:       {m['win_rate']:.1%}")
    print(f"  Take Rate:      {m['take_rate']:.1%}")
    print(f"  Profit Factor:  {m['profit_factor']:.2f}")
    print(f"  Avg R-Multiple: {m['avg_r_multiple']:+.3f}")
    print(f"  Sharpe Ratio:   {m['sharpe_ratio']:+.3f}")
    print(f"  Max Drawdown:   {m['max_drawdown']:.1f}%")
    print(f"  Mean Ep Reward: {m['mean_episode_reward']:+.3f}")
    print(f"  Trades Taken:   {m['total_trades_taken']}")
    print(f"  Signals Seen:   {m['total_signals_seen']}")

    # Failure analysis
    if "failures" in entry:
        fa = entry["failures"]
        print()
        print("  ── Failure Analysis ──")
        print(f"  Signals: {fa['total_signals']}  Taken: {fa['total_taken']}  "
              f"Wins: {fa['total_wins']}  Losses: {fa['total_losses']}  Vetoed: {fa['total_vetoed']}")

        if fa.get("exit_reasons"):
            print(f"  Exit reasons: {fa['exit_reasons']}")
        if fa.get("hold_duration"):
            hd = fa["hold_duration"]
            print(f"  Hold: <5m={hd['very_fast_0_5min']}  5-15m={hd['short_5_15min']}  15-30m={hd['mid_15_30min']}  30m+={hd['long_30plus_min']}")
        if fa.get("volatility"):
            for regime in ["low", "mid", "high"]:
                v = fa["volatility"][regime]
                print(f"  Vol {regime}: {v['losses']}/{v['total']} losses ({v['loss_rate']:.0%})")
        if fa.get("trend_alignment"):
            for align in ["aligned", "counter"]:
                t = fa["trend_alignment"][align]
                print(f"  Trend {align}: {t['losses']}/{t['total']} losses ({t['loss_rate']:.0%})")

        if fa.get("failure_clusters"):
            print()
            print("  ── Top Failure Clusters ──")
            for i, c in enumerate(fa["failure_clusters"], 1):
                print(f"  {i}. [{c['pattern']}] {c['description']}")
                print(f"     → Suggestion: {c['suggestion']}")

    # Trend
    if len(tracker) >= 2:
        prev = tracker[-2]["metrics"]
        curr = m
        print()
        print("  ── Trend (vs previous) ──")
        for key in ["win_rate", "avg_r_multiple", "sharpe_ratio", "profit_factor"]:
            delta = curr[key] - prev[key]
            arrow = "▲" if delta > 0 else "▼" if delta < 0 else "▬"
            print(f"  {arrow} {key}: {delta:+.4f}")
    print()
    print(f"  Tracker saved → {TRACKER_PATH} ({len(tracker)} entries)")
    print("=" * 60)


if __name__ == "__main__":
    main()
