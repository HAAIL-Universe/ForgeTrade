"""Tests for app.rl.rewards — Reward shaping components."""

import pytest
from app.rl.rewards import (
    AccountState,
    RewardConfig,
    TradeOutcomeForReward,
    calculate_reward,
)


def _out(r: float = 0.0, hold: int = 15, pnl: float = 0.0, reason: str = "tp_hit"):
    return TradeOutcomeForReward(r_multiple=r, hold_minutes=hold, pnl=pnl, exit_reason=reason)


class TestAccountState:
    def test_drawdown_pct(self):
        a = AccountState(equity=9500, peak_equity=10000)
        assert abs(a.drawdown_pct - 5.0) < 0.01

    def test_no_drawdown(self):
        a = AccountState(equity=10000, peak_equity=10000)
        assert a.drawdown_pct == 0.0

    def test_zero_peak(self):
        a = AccountState(equity=0, peak_equity=0)
        assert a.drawdown_pct == 0.0  # Guard against divide-by-zero


class TestCoreReward:
    def test_take_win_returns_r_multiple(self):
        r = calculate_reward(1, _out(r=1.5), _out(r=1.5), AccountState())
        assert r > 1.0  # Core component is 1.5

    def test_take_loss_returns_negative(self):
        r = calculate_reward(1, _out(r=-1.0), _out(r=-1.0), AccountState())
        assert r < 0

    def test_correct_veto(self):
        """Vetoing a loser → positive reward."""
        r = calculate_reward(0, None, _out(r=-0.8), AccountState())
        assert r == pytest.approx(0.3)  # correct_veto_reward

    def test_incorrect_veto(self):
        """Vetoing a winner → penalty."""
        r = calculate_reward(0, None, _out(r=1.2), AccountState())
        assert r == pytest.approx(-0.15)  # missed_winner_penalty


class TestDurationPenalty:
    def test_short_hold_no_penalty(self):
        cfg = RewardConfig()
        r = calculate_reward(1, _out(r=1.0, hold=10), _out(r=1.0), AccountState(), cfg)
        # Core=1.0, no duration penalty for hold < 30min
        assert r >= 1.0 - 0.01  # Might have minor DD/streak adjustments

    def test_moderate_hold_penalty(self):
        cfg = RewardConfig()
        r_short = calculate_reward(1, _out(r=1.0, hold=10), _out(r=1.0), AccountState(), cfg)
        r_moderate = calculate_reward(1, _out(r=1.0, hold=45), _out(r=1.0), AccountState(), cfg)
        assert r_moderate < r_short  # Moderate penalty applied

    def test_long_hold_penalty(self):
        cfg = RewardConfig()
        r_moderate = calculate_reward(1, _out(r=1.0, hold=45), _out(r=1.0), AccountState(), cfg)
        r_long = calculate_reward(1, _out(r=1.0, hold=90), _out(r=1.0), AccountState(), cfg)
        assert r_long < r_moderate

    def test_time_exit_max_penalty(self):
        cfg = RewardConfig()
        r_long = calculate_reward(1, _out(r=1.0, hold=90), _out(r=1.0), AccountState(), cfg)
        r_timeout = calculate_reward(1, _out(r=1.0, hold=180), _out(r=1.0), AccountState(), cfg)
        assert r_timeout < r_long


class TestDrawdownAmplification:
    def test_no_amplification_on_win(self):
        """Winning trade should not trigger drawdown penalty."""
        a = AccountState(equity=9400, peak_equity=10000)  # 6% DD
        r = calculate_reward(1, _out(r=1.5, hold=10), _out(r=1.5), a)
        assert r >= 1.0  # No DD penalty on wins

    def test_warning_level_amplification(self):
        """Loss during 3-5% drawdown → 2× penalty."""
        a_low = AccountState(equity=10000, peak_equity=10000)  # 0% DD
        a_warn = AccountState(equity=9600, peak_equity=10000)  # 4% DD
        r_low = calculate_reward(1, _out(r=-1.0, hold=10), _out(r=-1.0), a_low)
        r_warn = calculate_reward(1, _out(r=-1.0, hold=10), _out(r=-1.0), a_warn)
        assert r_warn < r_low  # Higher DD → bigger penalty

    def test_danger_level_amplification(self):
        """Loss during >5% drawdown → 3× penalty."""
        a_warn = AccountState(equity=9600, peak_equity=10000)  # 4% DD
        a_danger = AccountState(equity=9400, peak_equity=10000)  # 6% DD
        r_warn = calculate_reward(1, _out(r=-1.0, hold=10), _out(r=-1.0), a_warn)
        r_danger = calculate_reward(1, _out(r=-1.0, hold=10), _out(r=-1.0), a_danger)
        assert r_danger < r_warn


class TestStreakAwareness:
    def test_winning_streak_bonus(self):
        """Three consecutive winners + another win → bonus."""
        a = AccountState(recent_trades=[1.0, 0.5, 1.2])
        r_no_streak = calculate_reward(1, _out(r=1.0, hold=10), _out(r=1.0), AccountState())
        r_streak = calculate_reward(1, _out(r=1.0, hold=10), _out(r=1.0), a)
        assert r_streak > r_no_streak

    def test_losing_streak_penalty(self):
        """Three consecutive losers + another loss → extra penalty."""
        a = AccountState(recent_trades=[-1.0, -0.5, -1.2])
        r_no_streak = calculate_reward(1, _out(r=-1.0, hold=10), _out(r=-1.0), AccountState())
        r_streak = calculate_reward(1, _out(r=-1.0, hold=10), _out(r=-1.0), a)
        assert r_streak < r_no_streak

    def test_no_streak_effect_when_insufficient_history(self):
        """Fewer than lookback trades → no streak effect."""
        a = AccountState(recent_trades=[1.0, 0.5])  # Only 2 trades
        r1 = calculate_reward(1, _out(r=1.0, hold=10), _out(r=1.0), AccountState())
        r2 = calculate_reward(1, _out(r=1.0, hold=10), _out(r=1.0), a)
        assert abs(r1 - r2) < 0.01


class TestRewardClipping:
    def test_clip_upper(self):
        cfg = RewardConfig(reward_max=2.0)
        r = calculate_reward(1, _out(r=5.0, hold=5), _out(r=5.0), AccountState(), cfg)
        assert r <= 2.0

    def test_clip_lower(self):
        cfg = RewardConfig(reward_min=-2.0)
        a = AccountState(equity=9000, peak_equity=10000, recent_trades=[-1, -1, -1])
        r = calculate_reward(1, _out(r=-5.0, hold=200), _out(r=-5.0), a, cfg)
        assert r >= -2.0


class TestVetoHasNoSideEffects:
    def test_veto_no_duration_penalty(self):
        """VETO reward ignores duration penalty."""
        r1 = calculate_reward(0, None, _out(r=-1.0, hold=10), AccountState())
        r2 = calculate_reward(0, None, _out(r=-1.0, hold=200), AccountState())
        assert r1 == r2  # Duration of counterfactual doesn't affect veto reward
