"""Reward shaping for ForgeAgent RL training.

Four-component reward:
1. Trade outcome (core R-multiple or counterfactual veto scoring)
2. Hold duration penalty
3. Drawdown contribution cost
4. Streak awareness bonus/penalty
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ── Account state ────────────────────────────────────────────────────────


@dataclass
class AccountState:
    """Tracks account state across an RL episode for reward computation."""

    equity: float = 10_000.0
    peak_equity: float = 10_000.0
    recent_trades: list[float] = field(default_factory=list)  # R-multiples

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown as percentage of peak equity."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100.0)


# ── Trade outcome (lightweight — used by reward calc) ────────────────────


@dataclass
class TradeOutcomeForReward:
    """Minimal trade result for reward computation."""

    r_multiple: float = 0.0
    hold_minutes: int = 0
    pnl: float = 0.0
    exit_reason: str = ""


# ── Reward config ────────────────────────────────────────────────────────


@dataclass
class RewardConfig:
    """Tunable reward parameters."""

    # Veto scoring
    correct_veto_reward: float = 0.3
    missed_winner_penalty: float = -0.15

    # Duration thresholds (minutes)
    ideal_hold_max: int = 30
    moderate_hold_max: int = 60
    long_hold_max: int = 120

    # Duration penalties
    moderate_hold_penalty: float = -0.05
    long_hold_penalty: float = -0.15
    time_exit_penalty: float = -0.3

    # Drawdown amplification
    dd_warning_threshold: float = 3.0   # 3%
    dd_danger_threshold: float = 5.0    # 5%
    dd_warning_multiplier: float = 2.0
    dd_danger_multiplier: float = 3.0

    # Streak
    losing_streak_extra_penalty: float = -0.15
    winning_streak_bonus: float = 0.1
    streak_lookback: int = 3

    # Reward clipping
    reward_min: float = -2.0
    reward_max: float = 2.0


# ── Reward function ──────────────────────────────────────────────────────


def calculate_reward(
    action: int,
    trade_outcome,  # TradeOutcome from environment, or None if VETO
    counterfactual_outcome,  # Always simulated — what WOULD have happened
    account_state: AccountState,
    config: Optional[RewardConfig] = None,
) -> float:
    """Calculate the shaped reward for a single step.

    Args:
        action: 0 = VETO, 1 = TAKE.
        trade_outcome: Actual trade result (only when action=1).
        counterfactual_outcome: What would have happened regardless.
        account_state: Current account state.
        config: Reward configuration.

    Returns:
        Scalar reward clipped to [config.reward_min, config.reward_max].
    """
    if config is None:
        config = RewardConfig()

    # ── Component 1: Core trade outcome reward ──────────────────────
    if action == 0:  # VETO
        if counterfactual_outcome.r_multiple < 0:
            # Correctly vetoed a loser
            reward_core = config.correct_veto_reward
        else:
            # Incorrectly vetoed a winner
            reward_core = config.missed_winner_penalty
        # No duration, drawdown, or streak components for vetoes
        total = reward_core
        return float(np.clip(total, config.reward_min, config.reward_max))

    # action == 1: TAKE
    reward_core = trade_outcome.r_multiple

    # ── Component 2: Hold duration penalty ──────────────────────────
    duration_penalty = 0.0
    hold_min = trade_outcome.hold_minutes

    if hold_min <= config.ideal_hold_max:
        duration_penalty = 0.0
    elif hold_min <= config.moderate_hold_max:
        duration_penalty = config.moderate_hold_penalty
    elif hold_min <= config.long_hold_max:
        duration_penalty = config.long_hold_penalty
    else:
        duration_penalty = config.time_exit_penalty

    # ── Component 3: Drawdown contribution cost ─────────────────────
    drawdown_penalty = 0.0
    if trade_outcome.r_multiple < 0:
        dd_before = account_state.drawdown_pct
        # Estimate DD increase from this loss
        risk_pct = 2.0  # Matches live config
        dd_increase = abs(trade_outcome.r_multiple) * risk_pct

        if dd_before > config.dd_danger_threshold:
            drawdown_penalty = -dd_increase * config.dd_danger_multiplier / 100.0
        elif dd_before > config.dd_warning_threshold:
            drawdown_penalty = -dd_increase * config.dd_warning_multiplier / 100.0
        else:
            drawdown_penalty = -dd_increase * 1.0 / 100.0

    # ── Component 4: Streak awareness ───────────────────────────────
    streak_bonus = 0.0
    recent = account_state.recent_trades
    lookback = config.streak_lookback

    if len(recent) >= lookback:
        last_n = recent[-lookback:]
        wins = sum(1 for r in last_n if r > 0)

        if wins == lookback and trade_outcome.r_multiple > 0:
            streak_bonus = config.winning_streak_bonus
        elif wins == 0 and trade_outcome.r_multiple < 0:
            streak_bonus = config.losing_streak_extra_penalty

    # ── Combined reward ─────────────────────────────────────────────
    total = reward_core + duration_penalty + drawdown_penalty + streak_bonus
    return float(np.clip(total, config.reward_min, config.reward_max))
