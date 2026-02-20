"""Auto-iterate: Train → Evaluate → Analyze Failures → Nudge → Repeat.

Deterministic hill-climbing optimiser. No LLM calls. Reads failure
clusters from each evaluation and applies small, bounded parameter
adjustments to the RL environment config, then retrains and re-evaluates.

Modes:
  Bounded:     python -m scripts.auto_iterate --iterations 5
  Continuous:  python -m scripts.auto_iterate --continuous
  Dry run:     python -m scripts.auto_iterate --iterations 3 --dry-run

Continuous mode runs forever (or until targets are met), sleeping between
iterations to let the machine cool.  Targets:
  --target-win-rate 0.45   (stop when win rate >= 45%)
  --target-avg-r    0.02   (stop when avg R >= +0.02)
  --target-pf       1.1    (stop when profit factor >= 1.1)

The tracker (data/agent_training_tracker.json) records every iteration.
All changes are viewable in the dashboard Forge Agent panel.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.rl.environment import EnvConfig
from app.rl.rewards import RewardConfig
from app.rl.train import train as run_training
from scripts.eval_agent import (
    run_evaluation,
    load_tracker,
    save_tracker,
    TRACKER_PATH,
)

logger = logging.getLogger("forgetrade.auto_iterate")

ITERATE_STATE_PATH = Path("data") / "iterate_state.json"


# ── Parameter bounds ─────────────────────────────────────────────────────

# Each tunable parameter: (min, max, step_size)
PARAM_BOUNDS: dict[str, tuple[float, float, float]] = {
    # EnvConfig
    "rr_ratio":             (1.5, 5.0, 0.25),
    "max_hold_minutes":     (30, 240, 15),
    "bias_lookback":        (8, 30, 2),
    "ema_pullback_period":  (5, 15, 1),
    "max_drawdown_pct":     (5.0, 15.0, 1.0),

    # RewardConfig
    "correct_veto_reward":  (0.1, 0.8, 0.05),
    "missed_winner_penalty": (-0.5, -0.05, 0.05),
    "ideal_hold_max":       (10, 60, 5),
    "dd_warning_threshold": (1.5, 5.0, 0.5),
    "dd_danger_threshold":  (3.0, 8.0, 0.5),
}

# ── Failure pattern → parameter mapping ──────────────────────────────────
# Each rule: pattern → (parameter_name, direction, config_target)
# direction: +1 = increase, -1 = decrease

NUDGE_RULES: list[dict] = [
    {
        "pattern": "low_volatility",
        "param": "bias_lookback",
        "direction": +1,
        "config": "env",
        "reason": "Low-vol losses → increase lookback to require stronger trends",
    },
    {
        "pattern": "counter_trend",
        "param": "bias_lookback",
        "direction": +1,
        "config": "env",
        "reason": "Counter-trend losses → longer lookback for more reliable bias",
    },
    {
        "pattern": "fast_sl_hit",
        "param": "rr_ratio",
        "direction": -1,
        "config": "env",
        "reason": "Fast SL hits → tighter R:R to reduce required move size",
    },
    {
        "pattern": "time_exits",
        "param": "max_hold_minutes",
        "direction": -1,
        "config": "env",
        "reason": "Time exits dominate → reduce max hold to cut stale trades",
    },
    {
        "pattern": "time_exits",
        "param": "ideal_hold_max",
        "direction": -1,
        "config": "reward",
        "reason": "Time exits dominate → penalise long holds earlier",
    },
    {
        "pattern": "high_spread",
        "param": "ema_pullback_period",
        "direction": -1,
        "config": "env",
        "reason": "High-spread losses → faster EMA for tighter pullback entry",
    },
    {
        "pattern": "bad_session_hour",
        "param": "correct_veto_reward",
        "direction": +1,
        "config": "reward",
        "reason": "Session-hour losses → reward vetoing more to encourage selectivity",
    },
]

# ── Fallback nudges (when no specific failure cluster matches) ───────────

FALLBACK_NUDGES: list[dict] = [
    {"param": "correct_veto_reward", "direction": +1, "config": "reward",
     "reason": "No strong cluster — nudge agent toward more selective vetoing"},
    {"param": "rr_ratio", "direction": +1, "config": "env",
     "reason": "No strong cluster — try better R:R"},
]


# ── State persistence ────────────────────────────────────────────────────


def load_iterate_state() -> dict:
    """Load iteration state (tracks which nudges have been applied)."""
    if ITERATE_STATE_PATH.exists():
        return json.loads(ITERATE_STATE_PATH.read_text())
    return {
        "iteration": 0,
        "env_config": asdict(EnvConfig()),
        "reward_config": asdict(RewardConfig()),
        "nudge_history": [],
        "best_avg_r": -999.0,
        "best_iteration": 0,
    }


def save_iterate_state(state: dict) -> None:
    ITERATE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ITERATE_STATE_PATH.write_text(json.dumps(state, indent=2, default=str))


# ── Core: apply a nudge ─────────────────────────────────────────────────


def apply_nudge(
    env_config: dict,
    reward_config: dict,
    param: str,
    direction: int,
) -> tuple[dict, dict, float, float]:
    """Apply a single parameter nudge within bounds.

    Returns: (env_config, reward_config, old_value, new_value)
    """
    bounds = PARAM_BOUNDS.get(param)
    if bounds is None:
        return env_config, reward_config, 0.0, 0.0

    lo, hi, step = bounds

    # Find which config dict holds this param
    if param in env_config:
        old_val = env_config[param]
        new_val = old_val + (step * direction)
        new_val = max(lo, min(hi, new_val))
        env_config[param] = type(old_val)(new_val) if isinstance(old_val, int) else round(new_val, 4)
        return env_config, reward_config, old_val, env_config[param]
    elif param in reward_config:
        old_val = reward_config[param]
        new_val = old_val + (step * direction)
        new_val = max(lo, min(hi, new_val))
        reward_config[param] = round(new_val, 4)
        return env_config, reward_config, old_val, reward_config[param]

    return env_config, reward_config, 0.0, 0.0


# ── Core: pick nudge from failure analysis ───────────────────────────────


def pick_nudge(
    failures: dict | None,
    nudge_history: list[dict],
) -> dict | None:
    """Select the best nudge based on failure clusters.

    Avoids repeating the exact same nudge consecutively.
    Returns a nudge rule dict or None.
    """
    if not failures or not failures.get("failure_clusters"):
        # No failures data — use fallback
        for fb in FALLBACK_NUDGES:
            last = nudge_history[-1] if nudge_history else {}
            if last.get("param") != fb["param"]:
                return fb
        return FALLBACK_NUDGES[0]

    clusters = failures["failure_clusters"]
    patterns_present = {c["pattern"] for c in clusters}

    # Find matching rules, prioritised by cluster impact order
    for cluster in clusters:
        pattern = cluster["pattern"]
        for rule in NUDGE_RULES:
            if rule["pattern"] == pattern:
                # Check we're not repeating the exact same nudge
                last = nudge_history[-1] if nudge_history else {}
                if last.get("param") == rule["param"] and last.get("direction") == rule["direction"]:
                    continue  # Skip — try different rule
                return rule

    # Nothing matched — fallback
    for fb in FALLBACK_NUDGES:
        last = nudge_history[-1] if nudge_history else {}
        if last.get("param") != fb["param"]:
            return fb
    return FALLBACK_NUDGES[0]


# ── Core: revert if worse ───────────────────────────────────────────────


def should_revert(
    current_metrics: dict,
    previous_metrics: dict | None,
    tolerance: float = 0.005,
) -> bool:
    """Return True if the current iteration is meaningfully worse."""
    if previous_metrics is None:
        return False
    prev_r = previous_metrics.get("avg_r_multiple", -999)
    curr_r = current_metrics.get("avg_r_multiple", -999)
    # Worse by more than tolerance
    return curr_r < prev_r - tolerance


# ── Convergence targets ──────────────────────────────────────────────────

DEFAULT_TARGETS = {
    "win_rate": 0.45,        # 45%
    "avg_r_multiple": 0.02,  # Slightly positive
    "profit_factor": 1.1,    # At least profitable
}

def targets_met(metrics: dict, targets: dict) -> bool:
    """Return True when ALL convergence targets are satisfied."""
    return (
        metrics.get("win_rate", 0) >= targets.get("win_rate", 1.0) and
        metrics.get("avg_r_multiple", -999) >= targets.get("avg_r_multiple", 999) and
        metrics.get("profit_factor", 0) >= targets.get("profit_factor", 999)
    )


# ── Status file for dashboard ───────────────────────────────────────────

STATUS_PATH = Path("data") / "iterate_status.json"

def write_status(state: dict, phase: str, detail: str = "") -> None:
    """Write a lightweight status file the dashboard can poll."""
    status = {
        "iteration": state.get("iteration", 0),
        "phase": phase,           # idle | training | evaluating | nudging | sleeping | converged
        "detail": detail,
        "best_avg_r": state.get("best_avg_r", -999),
        "best_iteration": state.get("best_iteration", 0),
        "last_nudge": state["nudge_history"][-1] if state.get("nudge_history") else None,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2, default=str))


# ── Main iteration loop ─────────────────────────────────────────────────


def auto_iterate(
    iterations: int = 3,
    timesteps: int = 150_000,
    eval_episodes: int = 10,
    instrument: str = "XAU_USD",
    dry_run: bool = False,
    continuous: bool = False,
    cooldown_secs: int = 30,
    targets: dict | None = None,
    max_iterations: int = 200,
) -> None:
    """Run the full auto-iterate loop.

    If *continuous* is True, loops until targets are met or
    *max_iterations* is reached, sleeping *cooldown_secs* between
    iterations.
    """
    if targets is None:
        targets = dict(DEFAULT_TARGETS)

    state = load_iterate_state()
    total_to_run = max_iterations if continuous else iterations
    converged = False

    for i in range(total_to_run):
        state["iteration"] += 1
        iteration = state["iteration"]
        logger.info("=" * 60)
        logger.info("  AUTO-ITERATE — Iteration %d%s", iteration,
                     " (continuous)" if continuous else "")
        logger.info("=" * 60)

        write_status(state, "nudging", "Selecting parameter nudge…")

        # ── Step 1: Pick nudge from last evaluation's failures ──
        tracker = load_tracker()
        last_entry = tracker[-1] if tracker else None
        last_failures = last_entry.get("failures") if last_entry else None
        last_metrics = last_entry.get("metrics") if last_entry else None

        # Check if we should revert the previous nudge
        if len(state["nudge_history"]) > 0 and len(tracker) >= 2:
            prev_metrics = tracker[-2].get("metrics")
            if should_revert(last_metrics, prev_metrics):
                last_nudge = state["nudge_history"][-1]
                logger.info(
                    "  Previous nudge made things worse — REVERTING %s",
                    last_nudge["param"],
                )
                # Reverse direction
                state["env_config"], state["reward_config"], _, _ = apply_nudge(
                    state["env_config"],
                    state["reward_config"],
                    last_nudge["param"],
                    -last_nudge["direction"],
                )
                state["nudge_history"].append({
                    "iteration": iteration,
                    "param": last_nudge["param"],
                    "direction": -last_nudge["direction"],
                    "reason": "REVERT — previous nudge worsened metrics",
                    "reverted": True,
                })

        nudge = pick_nudge(last_failures, state["nudge_history"])

        if nudge:
            logger.info("  Nudge: %s %s by %s (reason: %s)",
                        "increase" if nudge["direction"] > 0 else "decrease",
                        nudge["param"],
                        PARAM_BOUNDS.get(nudge["param"], (0, 0, 0))[2],
                        nudge["reason"])

            env_before = copy.deepcopy(state["env_config"])
            reward_before = copy.deepcopy(state["reward_config"])

            state["env_config"], state["reward_config"], old_v, new_v = apply_nudge(
                state["env_config"],
                state["reward_config"],
                nudge["param"],
                nudge["direction"],
            )

            state["nudge_history"].append({
                "iteration": iteration,
                "param": nudge["param"],
                "direction": nudge["direction"],
                "old_value": old_v,
                "new_value": new_v,
                "reason": nudge["reason"],
                "reverted": False,
            })

            logger.info("  %s: %s → %s", nudge["param"], old_v, new_v)
        else:
            logger.info("  No nudge to apply this iteration")

        if dry_run:
            logger.info("  [DRY RUN] Would train with: %s", json.dumps(state["env_config"], indent=2))
            save_iterate_state(state)
            write_status(state, "idle", "Dry run — no training")
            continue

        # ── Step 2: Train ──
        write_status(state, "training", f"Training {timesteps:,} timesteps…")
        logger.info("  Training %d timesteps…", timesteps)
        env_cfg = EnvConfig(**{k: v for k, v in state["env_config"].items() if k in EnvConfig.__dataclass_fields__})
        reward_cfg = RewardConfig(**{k: v for k, v in state["reward_config"].items() if k in RewardConfig.__dataclass_fields__})

        run_training(
            instrument=instrument,
            total_timesteps=timesteps,
            env_config=env_cfg,
            reward_config=reward_cfg,
            seed=42 + iteration,
        )

        # ── Step 3: Evaluate ──
        write_status(state, "evaluating", f"Evaluating {eval_episodes} episodes…")
        logger.info("  Evaluating…")
        label = f"iter-{iteration}"
        if nudge:
            label += f"-{nudge['param']}"

        entry = run_evaluation(
            model_path="models/forge_agent/best_model.zip",
            instrument=instrument,
            n_episodes=eval_episodes,
            label=label,
            include_failures=True,
            env_config=env_cfg,
            reward_config=reward_cfg,
        )

        # Add iteration context
        entry["iteration"] = iteration
        entry["nudge"] = state["nudge_history"][-1] if state["nudge_history"] else None
        entry["env_config"] = copy.deepcopy(state["env_config"])
        entry["reward_config"] = copy.deepcopy(state["reward_config"])

        # Append to tracker
        tracker = load_tracker()
        tracker.append(entry)
        save_tracker(tracker)

        # Track best
        curr_r = entry["metrics"]["avg_r_multiple"]
        if curr_r > state["best_avg_r"]:
            state["best_avg_r"] = curr_r
            state["best_iteration"] = iteration
            logger.info("  ★ New best avg_r_multiple: %+.4f (iteration %d)", curr_r, iteration)

        save_iterate_state(state)

        # Print summary
        m = entry["metrics"]
        logger.info(
            "  Result: win=%.1f%% take=%.1f%% avgR=%+.3f PF=%.2f DD=%.1f%% reward=%+.2f",
            m["win_rate"] * 100, m["take_rate"] * 100, m["avg_r_multiple"],
            m["profit_factor"], m["max_drawdown"], m["mean_episode_reward"],
        )

        if entry.get("failures", {}).get("failure_clusters"):
            clusters = entry["failures"]["failure_clusters"]
            logger.info("  Top clusters: %s", ", ".join(c["pattern"] for c in clusters[:3]))

        # ── Step 4: Check convergence (continuous mode) ──
        if continuous and targets_met(m, targets):
            logger.info("  ★★★ TARGETS MET — stopping auto-iterate ★★★")
            logger.info("  win_rate=%.1f%% (target %.1f%%) | avg_r=%+.4f (target %+.4f) | PF=%.2f (target %.2f)",
                        m["win_rate"] * 100, targets["win_rate"] * 100,
                        m["avg_r_multiple"], targets["avg_r_multiple"],
                        m["profit_factor"], targets["profit_factor"])
            write_status(state, "converged", "Targets met!")
            converged = True
            break

        # Cooldown between iterations
        if continuous and i < total_to_run - 1:
            write_status(state, "sleeping", f"Cooldown {cooldown_secs}s before next iteration…")
            logger.info("  Sleeping %ds before next iteration…", cooldown_secs)
            time.sleep(cooldown_secs)

    # Final summary
    logger.info("\n" + "=" * 60)
    if converged:
        logger.info("  AUTO-ITERATE CONVERGED after %d iterations", state["iteration"])
    else:
        logger.info("  AUTO-ITERATE COMPLETE — %d iterations", state["iteration"])
    logger.info("  Best avg R-multiple: %+.4f (iteration %d)",
                state["best_avg_r"], state["best_iteration"])
    logger.info("  Tracker: %s (%d entries)", TRACKER_PATH, len(load_tracker()))
    logger.info("=" * 60)
    write_status(state, "idle", "Finished")


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Auto-iterate ForgeAgent: train → eval → nudge → repeat",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run 5 iterations with 100K timesteps each
  python -m scripts.auto_iterate --iterations 5 --timesteps 100000

  # Run continuously until targets are met
  python -m scripts.auto_iterate --continuous --timesteps 150000

  # Continuous with custom targets
  python -m scripts.auto_iterate --continuous --target-win-rate 0.5 --target-avg-r 0.05

  # Dry run — show what would change without training
  python -m scripts.auto_iterate --iterations 3 --dry-run
""",
    )
    parser.add_argument("--iterations", type=int, default=3, help="Number of train/eval cycles (bounded mode)")
    parser.add_argument("--continuous", action="store_true", help="Run until convergence targets are met")
    parser.add_argument("--max-iterations", type=int, default=200, help="Safety cap for continuous mode")
    parser.add_argument("--timesteps", type=int, default=150_000, help="Training timesteps per iteration")
    parser.add_argument("--episodes", type=int, default=10, help="Eval episodes per iteration")
    parser.add_argument("--cooldown", type=int, default=30, help="Seconds between iterations (continuous)")
    parser.add_argument("--instrument", default="XAU_USD")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without training")
    parser.add_argument("--target-win-rate", type=float, default=0.45, help="Target win rate (0-1)")
    parser.add_argument("--target-avg-r", type=float, default=0.02, help="Target avg R-multiple")
    parser.add_argument("--target-pf", type=float, default=1.1, help="Target profit factor")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    custom_targets = {
        "win_rate": args.target_win_rate,
        "avg_r_multiple": args.target_avg_r,
        "profit_factor": args.target_pf,
    }

    auto_iterate(
        iterations=args.iterations,
        timesteps=args.timesteps,
        eval_episodes=args.episodes,
        instrument=args.instrument,
        dry_run=args.dry_run,
        continuous=args.continuous,
        cooldown_secs=args.cooldown,
        targets=custom_targets,
        max_iterations=args.max_iterations,
    )


if __name__ == "__main__":
    main()
