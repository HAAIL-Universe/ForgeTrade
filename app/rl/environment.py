"""Gymnasium environment for ForgeAgent RL training.

Replays historical Gold candle data, presents state vectors to the agent,
simulates trade execution at M1 resolution, and computes rewards.
"""

from __future__ import annotations

import bisect
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime as _dt
from typing import Any, Optional

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from app.rl.features import (
    STATE_DIM,
    AccountSnapshot,
    ForgeStateBuilder,
)
from app.rl.rewards import AccountState, RewardConfig, calculate_reward
from app.strategy.indicators import calculate_atr, calculate_ema
from app.strategy.models import CandleData
from app.strategy.scalp_signals import evaluate_scalp_entry
from app.strategy.trend import detect_scalp_bias

logger = logging.getLogger("forgetrade.rl.env")


# ── Trade outcome ────────────────────────────────────────────────────────


@dataclass
class TradeOutcome:
    """Result of a simulated trade."""

    exit_price: float
    exit_reason: str  # "sl_hit" | "tp_hit" | "time_exit"
    hold_minutes: int
    pnl_pips: float
    r_multiple: float


def simulate_trade(
    entry_price: float,
    direction: str,
    sl: float,
    tp: float,
    m1_candles: list[CandleData],
    max_hold_minutes: int = 120,
    pip_value: float = 0.01,
) -> TradeOutcome:
    """Simulate a trade through M1 candle data with pessimistic fills.

    Scans each M1 candle to check SL/TP hit.  When both could trigger
    on the same candle, assumes SL hit first (conservative).
    """
    risk_pips = abs(entry_price - sl) / pip_value
    if risk_pips == 0:
        risk_pips = 1.0  # prevent division by zero

    for i, candle in enumerate(m1_candles):
        if i >= max_hold_minutes:
            break

        if direction == "buy":
            sl_hit = candle.low <= sl
            tp_hit = candle.high >= tp
        else:  # sell
            sl_hit = candle.high >= sl
            tp_hit = candle.low <= tp

        # Pessimistic: if both hit on same candle, assume SL first
        if sl_hit and tp_hit:
            pnl = sl - entry_price if direction == "buy" else entry_price - sl
            return TradeOutcome(
                exit_price=sl,
                exit_reason="sl_hit",
                hold_minutes=i + 1,
                pnl_pips=pnl / pip_value,
                r_multiple=(pnl / pip_value) / risk_pips,
            )

        if sl_hit:
            pnl = sl - entry_price if direction == "buy" else entry_price - sl
            return TradeOutcome(
                exit_price=sl,
                exit_reason="sl_hit",
                hold_minutes=i + 1,
                pnl_pips=pnl / pip_value,
                r_multiple=(pnl / pip_value) / risk_pips,
            )

        if tp_hit:
            pnl = tp - entry_price if direction == "buy" else entry_price - tp
            return TradeOutcome(
                exit_price=tp,
                exit_reason="tp_hit",
                hold_minutes=i + 1,
                pnl_pips=pnl / pip_value,
                r_multiple=(pnl / pip_value) / risk_pips,
            )

    # Time exit — close at last candle's close
    if m1_candles:
        exit_p = m1_candles[min(max_hold_minutes - 1, len(m1_candles) - 1)].close
    else:
        exit_p = entry_price

    pnl = exit_p - entry_price if direction == "buy" else entry_price - exit_p
    return TradeOutcome(
        exit_price=exit_p,
        exit_reason="time_exit",
        hold_minutes=min(max_hold_minutes, len(m1_candles)),
        pnl_pips=pnl / pip_value,
        r_multiple=(pnl / pip_value) / risk_pips,
    )


# ── SL/TP calculation (offline, no broker) ───────────────────────────────


def _offline_scalp_sl(
    entry_price: float,
    direction: str,
    m5_candles: list[CandleData],
    pip_value: float = 0.01,
    buffer_pips: float = 30.0,
) -> Optional[float]:
    """Offline SL from recent M5 swing structure (mirrors scalp_sl_tp.py)."""
    recent = m5_candles[-10:] if len(m5_candles) >= 10 else m5_candles

    if direction == "buy":
        sl = min(c.low for c in recent) - buffer_pips * pip_value
        sl_pips = abs(entry_price - sl) / pip_value
    elif direction == "sell":
        sl = max(c.high for c in recent) + buffer_pips * pip_value
        sl_pips = abs(sl - entry_price) / pip_value
    else:
        return None

    if sl_pips < 200.0 or sl_pips > 800.0:
        return None
    return round(sl, 2)


def _offline_scalp_tp(
    entry_price: float,
    direction: str,
    sl_price: float,
    rr_ratio: float = 3.0,
) -> float:
    """Offline TP from fixed R:R ratio (mirrors scalp_sl_tp.py)."""
    risk = abs(entry_price - sl_price)
    reward = risk * rr_ratio
    if direction == "buy":
        return round(entry_price + reward, 2)
    else:
        return round(entry_price - reward, 2)


# ── Environment config ───────────────────────────────────────────────────


@dataclass
class EnvConfig:
    """Configuration for the ForgeTradeEnv."""

    instrument: str = "XAU_USD"
    pip_value: float = 0.01

    # Episode
    episode_length_days: int = 5
    max_steps_per_episode: int = 200

    # Trade simulation
    max_hold_minutes: int = 120
    risk_per_trade_pct: float = 2.0
    initial_equity: float = 10_000.0
    max_drawdown_pct: float = 10.0
    rr_ratio: float = 3.0

    # Signal generation
    bias_lookback: int = 15
    ema_pullback_period: int = 9

    # Feature computation
    atr_period: int = 14
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0


# ── Multi-timeframe aligned data ─────────────────────────────────────────


_TIME_FMTS = (
    "%Y-%m-%dT%H:%M:%S.%f+00:00",
    "%Y-%m-%dT%H:%M:%S+00:00",
    "%Y-%m-%d %H:%M:%S+00:00",
    "%Y-%m-%dT%H:%M:%S.%fZ",
    "%Y-%m-%dT%H:%M:%SZ",
)


def _parse_candle_ts(time_str: str) -> float:
    """Parse a CandleData.time string to epoch seconds for bisect lookups."""
    for fmt in _TIME_FMTS:
        try:
            return _dt.strptime(time_str, fmt).timestamp()
        except ValueError:
            continue
    return 0.0


@dataclass
class AlignedData:
    """Pre-aligned candle data across timeframes for efficient replay."""

    m1: list[CandleData] = field(default_factory=list)
    m5: list[CandleData] = field(default_factory=list)
    m15: list[CandleData] = field(default_factory=list)
    h1: list[CandleData] = field(default_factory=list)

    # Timestamp indexes for bisect-based alignment (built lazily)
    _m1_ts: list[float] = field(default_factory=list, repr=False)
    _m15_ts: list[float] = field(default_factory=list, repr=False)
    _h1_ts: list[float] = field(default_factory=list, repr=False)

    def _ensure_indexes(self) -> None:
        """Build timestamp indexes if not yet built."""
        if not self._m1_ts and self.m1:
            self._m1_ts = [_parse_candle_ts(c.time) for c in self.m1]
        if not self._m15_ts and self.m15:
            self._m15_ts = [_parse_candle_ts(c.time) for c in self.m15]
        if not self._h1_ts and self.h1:
            self._h1_ts = [_parse_candle_ts(c.time) for c in self.h1]

    def find_m1_after(self, ref_ts: float) -> int:
        """Return index of the first M1 candle at or after *ref_ts*."""
        self._ensure_indexes()
        return bisect.bisect_left(self._m1_ts, ref_ts)

    def find_m15_before(self, ref_ts: float) -> int:
        """Return index of last M15 candle at or before *ref_ts*."""
        self._ensure_indexes()
        idx = bisect.bisect_right(self._m15_ts, ref_ts)
        return max(0, idx)

    def find_h1_before(self, ref_ts: float) -> int:
        """Return index of last H1 candle at or before *ref_ts*."""
        self._ensure_indexes()
        idx = bisect.bisect_right(self._h1_ts, ref_ts)
        return max(0, idx)

    @staticmethod
    def from_dataframes(
        m1_df=None, m5_df=None, m15_df=None, h1_df=None
    ) -> "AlignedData":
        """Build from pandas DataFrames (from Parquet)."""

        def _df_to_candles(df) -> list[CandleData]:
            if df is None or df.empty:
                return []
            candles = []
            for _, row in df.iterrows():
                t = str(row["time"]) if "time" in row else ""
                candles.append(CandleData(
                    time=t,
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row.get("volume", 0)),
                ))
            return candles

        return AlignedData(
            m1=_df_to_candles(m1_df),
            m5=_df_to_candles(m5_df),
            m15=_df_to_candles(m15_df),
            h1=_df_to_candles(h1_df),
        )


# ── Gymnasium environment ────────────────────────────────────────────────


class ForgeTradeEnv(gym.Env):
    """Simulated Gold scalping environment for RL training.

    Observation: Box(27,) — ForgeState vector.
    Action: Discrete(2) — 0 = VETO, 1 = TAKE.

    The agent does NOT choose BUY/SELL. The existing strategy determines
    direction; the agent only decides whether to allow the trade.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        data: AlignedData,
        config: Optional[EnvConfig] = None,
        reward_config: Optional[RewardConfig] = None,
    ) -> None:
        super().__init__()

        self.data = data
        self.config = config or EnvConfig()
        self.reward_config = reward_config or RewardConfig()

        self.observation_space = spaces.Box(
            low=-10.0, high=10.0,
            shape=(STATE_DIM,),
            dtype=np.float32,
        )
        self.action_space = spaces.Discrete(2)  # 0=VETO, 1=TAKE

        self._state_builder = ForgeStateBuilder()

        # Pre-scan signals once (deterministic from data + config)
        self._all_signals: list[dict] = self._prescan_signals()

        # Episode state
        self._m5_idx: int = 0
        self._step_count: int = 0
        self._account: AccountState = AccountState()
        self._signals: list[dict] = []  # Slice for current episode
        self._signal_idx: int = 0

        # Episode statistics
        self._trades_taken: int = 0
        self._trades_won: int = 0
        self._total_signals: int = 0
        self._total_r: float = 0.0

    def _prescan_signals(self) -> list[dict]:
        """Scan M5 data for places where the rule-based strategy would signal."""
        signals = []
        m5 = self.data.m5
        m1 = self.data.m1

        if len(m5) < 20 or len(m1) < 20:
            return signals

        for i in range(20, len(m5)):
            window_m5 = m5[max(0, i - 20): i]
            pip_value = self.config.pip_value

            # Check for momentum bias
            bias = detect_scalp_bias(
                window_m5,
                lookback=self.config.bias_lookback,
                pip_value=pip_value,
            )
            if bias.direction == "flat":
                continue

            # Check ATR gate
            try:
                atr = calculate_atr(window_m5, 14)
                atr_pips = atr / pip_value
                if atr_pips < 80.0:
                    continue
            except ValueError:
                continue

            # Check for pullback to EMA
            try:
                ema_vals = calculate_ema(window_m5, 9)
                ema_cur = ema_vals[-1]
                if math.isnan(ema_cur):
                    continue
            except (ValueError, IndexError):
                continue

            last_close = window_m5[-1].close

            # Pullback proximity
            if bias.direction == "bullish" and last_close > ema_cur * 1.006:
                continue
            if bias.direction == "bearish" and last_close < ema_cur * 0.994:
                continue

            # Simplified confirmation — check for directional candle
            last_c = window_m5[-1]
            if bias.direction == "bullish" and last_c.close <= last_c.open:
                continue
            if bias.direction == "bearish" and last_c.close >= last_c.open:
                continue

            # Valid signal
            entry_price = last_close
            direction = "buy" if bias.direction == "bullish" else "sell"

            # Calculate SL
            sl = _offline_scalp_sl(entry_price, direction, window_m5, pip_value)
            if sl is None:
                continue

            # Calculate TP
            tp = _offline_scalp_tp(entry_price, direction, sl, self.config.rr_ratio)

            # Find corresponding M1 candles for trade simulation
            # Use timestamp-based alignment (not index-based)
            m5_ts = _parse_candle_ts(m5[i].time)
            m1_start = self.data.find_m1_after(m5_ts)
            m1_end = m1_start + self.config.max_hold_minutes
            m1_for_trade = m1[m1_start:m1_end]

            # Skip signals without enough M1 data for a valid simulation
            if len(m1_for_trade) < 10:
                continue

            # Gather context windows for feature building
            m5_context = m5[max(0, i - 100): i]
            # Use timestamp-based alignment for M15/H1 context
            m15_idx = self.data.find_m15_before(m5_ts)
            m15_context = self.data.m15[max(0, m15_idx - 30): m15_idx] if self.data.m15 else []
            h1_idx = self.data.find_h1_before(m5_ts)
            h1_context = self.data.h1[max(0, h1_idx - 50): h1_idx] if self.data.h1 else []

            # Estimate spread from M1 data
            if m1_for_trade:
                spread_pips = min(
                    (c.high - c.low) / pip_value for c in m1_for_trade[:5]
                ) if len(m1_for_trade) >= 1 else 3.0
            else:
                spread_pips = 3.0

            # M1 context for feature building
            m1_context = m1[max(0, m1_start - 20): m1_start]

            signals.append({
                "m5_idx": i,
                "entry_price": entry_price,
                "direction": direction,
                "sl": sl,
                "tp": tp,
                "m1_for_trade": m1_for_trade,
                "m5_context": m5_context,
                "m1_context": m1_context,
                "m15_context": m15_context,
                "h1_context": h1_context,
                "spread_pips": spread_pips,
            })

        return signals

    def reset(
        self,
        *,
        seed: Optional[int] = None,
        options: Optional[dict] = None,
    ) -> tuple[np.ndarray, dict]:
        """Reset to a random episode within the data."""
        super().reset(seed=seed)

        self._account = AccountState(
            equity=self.config.initial_equity,
            peak_equity=self.config.initial_equity,
        )
        self._step_count = 0
        self._trades_taken = 0
        self._trades_won = 0
        self._total_signals = 0
        self._total_r = 0.0

        # Use cached signals
        self._signals = self._all_signals
        if not self._signals:
            # If no signals found, return zero observation
            self._signal_idx = 0
            return np.zeros(STATE_DIM, dtype=np.float32), {"signals_found": 0}

        # Randomly pick a starting point within available signals
        max_start = max(0, len(self._signals) - self.config.max_steps_per_episode)
        if self.np_random is not None:
            self._signal_idx = int(self.np_random.integers(0, max(1, max_start + 1)))
        else:
            self._signal_idx = 0

        obs = self._get_obs()
        info = {"signals_found": len(self._signals)}
        return obs, info

    def _get_obs(self) -> np.ndarray:
        """Build observation from the current signal."""
        if self._signal_idx >= len(self._signals):
            return np.zeros(STATE_DIM, dtype=np.float32)

        sig = self._signals[self._signal_idx]
        account_snap = AccountSnapshot(
            drawdown_pct=self._account.drawdown_pct,
            max_drawdown_pct=self.config.max_drawdown_pct,
            recent_r_multiples=list(self._account.recent_trades[-5:]),
        )

        state = self._state_builder.build(
            m5_candles=sig["m5_context"],
            m1_candles=sig["m1_context"],
            h1_candles=sig["h1_context"],
            m15_candles=sig["m15_context"],
            account=account_snap,
            current_spread_pips=sig["spread_pips"],
            pip_value=self.config.pip_value,
        )
        return state.to_array()

    def step(self, action: int) -> tuple[np.ndarray, float, bool, bool, dict]:
        """Execute one step: VETO (0) or TAKE (1) the current signal.

        Returns: (obs, reward, terminated, truncated, info)
        """
        self._step_count += 1
        self._total_signals += 1
        terminated = False
        truncated = False
        info: dict[str, Any] = {}

        if self._signal_idx >= len(self._signals):
            return np.zeros(STATE_DIM, dtype=np.float32), 0.0, False, True, {"reason": "no_signals"}

        sig = self._signals[self._signal_idx]

        # Always simulate the counterfactual (for veto reward scoring)
        counterfactual = simulate_trade(
            entry_price=sig["entry_price"],
            direction=sig["direction"],
            sl=sig["sl"],
            tp=sig["tp"],
            m1_candles=sig["m1_for_trade"],
            max_hold_minutes=self.config.max_hold_minutes,
            pip_value=self.config.pip_value,
        )

        trade_outcome: Optional[TradeOutcome] = None

        if action == 1:  # TAKE
            trade_outcome = counterfactual  # Same simulation
            self._trades_taken += 1
            self._total_r += trade_outcome.r_multiple

            if trade_outcome.r_multiple > 0:
                self._trades_won += 1

            # Update account
            risk_amount = self._account.equity * (self.config.risk_per_trade_pct / 100.0)
            pnl_dollars = trade_outcome.r_multiple * risk_amount
            self._account.equity += pnl_dollars
            self._account.peak_equity = max(self._account.peak_equity, self._account.equity)
            self._account.recent_trades.append(trade_outcome.r_multiple)

            info["trade_result"] = trade_outcome.exit_reason
            info["r_multiple"] = trade_outcome.r_multiple
            info["hold_minutes"] = trade_outcome.hold_minutes

        # Calculate reward
        reward = calculate_reward(
            action=action,
            trade_outcome=trade_outcome,
            counterfactual_outcome=counterfactual,
            account_state=self._account,
            config=self.reward_config,
        )

        # Check termination: drawdown circuit breaker
        if self._account.drawdown_pct >= self.config.max_drawdown_pct:
            terminated = True
            info["reason"] = "circuit_breaker"

        # Advance to next signal
        self._signal_idx += 1

        # Check truncation: max steps or data exhaustion
        if self._step_count >= self.config.max_steps_per_episode:
            truncated = True
            info["reason"] = "max_steps"
        elif self._signal_idx >= len(self._signals):
            truncated = True
            info["reason"] = "data_exhausted"

        # Episode stats
        info["take_rate"] = (
            self._trades_taken / self._total_signals
            if self._total_signals > 0 else 0.0
        )
        info["win_rate"] = (
            self._trades_won / self._trades_taken
            if self._trades_taken > 0 else 0.0
        )
        info["avg_r"] = (
            self._total_r / self._trades_taken
            if self._trades_taken > 0 else 0.0
        )
        info["max_dd"] = self._account.drawdown_pct

        obs = self._get_obs() if not (terminated or truncated) else np.zeros(STATE_DIM, dtype=np.float32)
        return obs, reward, terminated, truncated, info


# ── Noise wrapper (anti-overfitting) ─────────────────────────────────────


class NoisyObservationWrapper(gym.ObservationWrapper):
    """Adds Gaussian noise to observations during training."""

    def __init__(self, env: gym.Env, noise_std: float = 0.02):
        super().__init__(env)
        self.noise_std = noise_std
        self.training = True

    def observation(self, obs: np.ndarray) -> np.ndarray:
        if self.training:
            noise = self.np_random.normal(0, self.noise_std, size=obs.shape).astype(
                np.float32
            )
            return obs + noise
        return obs
