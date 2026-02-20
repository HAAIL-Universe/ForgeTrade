"""Shadow mode performance analysis.

Reads the shadow log produced by ``ShadowLogger`` and calculates
what would have happened if ForgeAgent was in active mode.

Usage:
    python -m app.rl.analyze_shadow --log data/rl_shadow_log.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger("forgetrade.rl.shadow")


def analyze_shadow_log(log_path: str) -> dict:
    """Analyze shadow mode performance.

    Pairs agent decisions with actual outcomes and computes
    theoretical improvement metrics.
    """
    path = Path(log_path)
    if not path.exists():
        return {"error": f"Log file not found: {log_path}"}

    decisions: list[dict] = []
    outcomes: list[dict] = []

    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") == "outcome":
                outcomes.append(record)
            else:
                decisions.append(record)

    if not decisions:
        return {"error": "No decisions found in log"}

    # Match decisions with outcomes by timestamp proximity
    # Simple approach: pair sequentially
    paired = []
    outcome_idx = 0
    for dec in decisions:
        if outcome_idx < len(outcomes):
            paired.append({**dec, **outcomes[outcome_idx]})
            outcome_idx += 1

    # Analysis
    correct_veto = 0
    missed_winner = 0
    correct_take = 0
    incorrect_take = 0
    total = len(paired)

    for p in paired:
        agent_action = p.get("agent_action", "TAKE")
        r_mult = p.get("r_multiple", 0.0)

        if agent_action == "VETO" and r_mult < 0:
            correct_veto += 1
        elif agent_action == "VETO" and r_mult >= 0:
            missed_winner += 1
        elif agent_action == "TAKE" and r_mult >= 0:
            correct_take += 1
        elif agent_action == "TAKE" and r_mult < 0:
            incorrect_take += 1

    # Unfiltered metrics (all trades as if taken)
    all_r = [p.get("r_multiple", 0) for p in paired]
    unfiltered_wins = sum(1 for r in all_r if r > 0)
    unfiltered_win_rate = unfiltered_wins / max(total, 1)

    # Filtered metrics (only TAKE decisions)
    taken_r = [p.get("r_multiple", 0) for p in paired if p.get("agent_action") == "TAKE"]
    filtered_wins = sum(1 for r in taken_r if r > 0)
    filtered_win_rate = filtered_wins / max(len(taken_r), 1)

    veto_total = correct_veto + missed_winner
    veto_accuracy = correct_veto / max(veto_total, 1)

    take_rate = len(taken_r) / max(total, 1)

    # Activation recommendation
    activate = (
        veto_accuracy >= 0.60
        and (filtered_win_rate - unfiltered_win_rate) >= 0.03
        and take_rate >= 0.40
    )

    return {
        "total_decisions": total,
        "correct_veto": correct_veto,
        "missed_winner": missed_winner,
        "correct_take": correct_take,
        "incorrect_take": incorrect_take,
        "veto_accuracy": round(veto_accuracy, 3),
        "take_rate": round(take_rate, 3),
        "unfiltered_win_rate": round(unfiltered_win_rate, 3),
        "filtered_win_rate": round(filtered_win_rate, 3),
        "win_rate_improvement": round(filtered_win_rate - unfiltered_win_rate, 3),
        "recommendation": "ACTIVATE" if activate else "KEEP IN SHADOW",
        "activation_criteria": {
            "veto_accuracy_min_60pct": veto_accuracy >= 0.60,
            "win_rate_improvement_min_3pct": (filtered_win_rate - unfiltered_win_rate) >= 0.03,
            "take_rate_min_40pct": take_rate >= 0.40,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze ForgeAgent shadow mode performance")
    parser.add_argument("--log", default="data/rl_shadow_log.jsonl")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    result = analyze_shadow_log(args.log)
    print(json.dumps(result, indent=2))

    if "recommendation" in result:
        logger.info("Recommendation: %s", result["recommendation"])


if __name__ == "__main__":
    main()
