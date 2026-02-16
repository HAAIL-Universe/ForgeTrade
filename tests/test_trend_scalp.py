"""Tests for Phase 10 — Trend-Confirmed Micro-Scalp Strategy.

Covers: trend detection, scalp signals, scalp SL/TP, trailing stop, spread
filter, position count guard, strategy registry, TrendScalpStrategy.
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.risk.scalp_sl_tp import (
    MIN_SL_PIPS,
    MAX_SL_PIPS,
    calculate_scalp_sl,
    calculate_scalp_tp,
)
from app.risk.trailing_stop import TrailingStop
from app.strategy.base import StrategyProtocol
from app.strategy.models import CandleData, INSTRUMENT_PIP_VALUES
from app.strategy.scalp_signals import (
    ScalpEntrySignal,
    evaluate_scalp_entry,
    _is_bullish_engulfing,
    _is_hammer,
    _is_shooting_star,
)
from app.strategy.spread_filter import is_spread_acceptable
from app.strategy.trend import TrendState, detect_trend
from app.strategy.trend_scalp import TrendScalpStrategy


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_candles(prices: list[tuple], time_prefix="2025-01-01T") -> list[CandleData]:
    """Build candle list from (open, high, low, close) tuples."""
    result = []
    for i, (o, h, l, c) in enumerate(prices):
        result.append(CandleData(
            time=f"{time_prefix}{i:02d}:00:00Z",
            open=o, high=h, low=l, close=c, volume=100,
        ))
    return result


def _make_trending_candles(direction: str, count: int = 60) -> list[CandleData]:
    """Generate synthetic H1 candles with a clear trend.

    Bullish: rising prices from 2000 upward.
    Bearish: falling prices from 2100 downward.
    """
    candles = []
    if direction == "bullish":
        for i in range(count):
            base = 2000 + i * 2
            candles.append(CandleData(
                time=f"2025-01-01T{i:02d}:00:00Z",
                open=base, high=base + 3, low=base - 1, close=base + 2,
                volume=100,
            ))
    elif direction == "bearish":
        for i in range(count):
            base = 2100 - i * 2
            candles.append(CandleData(
                time=f"2025-01-01T{i:02d}:00:00Z",
                open=base, high=base + 1, low=base - 3, close=base - 2,
                volume=100,
            ))
    else:  # flat / choppy — EMAs interleave, price oscillates around both
        # Keep prices in a very tight range so EMAs cross repeatedly
        for i in range(count):
            offset = 0.3 if i % 2 == 0 else -0.3
            base = 2050 + offset
            candles.append(CandleData(
                time=f"2025-01-01T{i:02d}:00:00Z",
                open=base, high=base + 0.5, low=base - 0.5, close=2050.0,
                volume=100,
            ))
    return candles


# ── Trend Detection ──────────────────────────────────────────────────────


class TestTrendDetection:
    def test_trend_bullish(self):
        candles = _make_trending_candles("bullish", 60)
        trend = detect_trend(candles)
        assert trend.direction == "bullish"
        assert trend.ema_fast_value > trend.ema_slow_value
        assert trend.slope > 0

    def test_trend_bearish(self):
        candles = _make_trending_candles("bearish", 60)
        trend = detect_trend(candles)
        assert trend.direction == "bearish"
        assert trend.ema_fast_value < trend.ema_slow_value
        assert trend.slope < 0

    def test_trend_flat(self):
        candles = _make_trending_candles("flat", 60)
        trend = detect_trend(candles)
        assert trend.direction == "flat"

    def test_trend_insufficient_data(self):
        candles = _make_trending_candles("bullish", 10)
        trend = detect_trend(candles)
        assert trend.direction == "flat"
        assert trend.ema_fast_value == 0.0


# ── Scalp Signals ────────────────────────────────────────────────────────


class TestScalpSignals:
    def test_scalp_buy_with_trend(self):
        """Buy signal when bullish trend + pullback + bullish engulfing."""
        trend = TrendState(
            direction="bullish", ema_fast_value=2050, ema_slow_value=2040, slope=10,
        )
        # M1 candles: price pulls back to EMA(9) area then engulfs
        # Build candles: start high, pull back, then engulfing confirmation
        prices = []
        for i in range(12):
            base = 2052 - i * 0.5  # Gradual pullback from 2052 to ~2046
            prices.append((base, base + 0.5, base - 0.3, base - 0.2))
        # Add bearish candle then bullish engulfing
        prices.append((2046.0, 2046.2, 2045.5, 2045.6))  # bearish
        prices.append((2045.5, 2047.0, 2045.4, 2046.5))  # bullish engulfing
        candles_m1 = _make_candles(prices)
        s5 = _make_candles([(2046.0, 2046.3, 2045.9, 2046.2)])

        result = evaluate_scalp_entry(candles_m1, s5, trend)
        assert result is not None
        assert result.direction == "buy"
        assert "buy" in result.reason.lower()

    def test_scalp_counter_trend_buy_in_bearish(self):
        """Counter-trend buy allowed when strong reversal pattern in bearish trend."""
        trend = TrendState(
            direction="bearish", ema_fast_value=2040, ema_slow_value=2050, slope=-10,
        )
        # Create bullish engulfing pattern (strong reversal)
        prices = []
        for i in range(12):
            base = 2038 + i * 0.5
            prices.append((base, base + 0.5, base - 0.3, base + 0.2))
        prices.append((2045.0, 2045.2, 2044.5, 2044.6))
        prices.append((2044.5, 2046.0, 2044.4, 2045.5))
        candles_m1 = _make_candles(prices)
        s5 = _make_candles([(2045.0, 2045.3, 2044.9, 2045.2)])

        result = evaluate_scalp_entry(candles_m1, s5, trend)
        # Counter-trend buy allowed with strong reversal (bullish engulfing)
        assert result is not None
        assert result.direction == "buy"
        assert "Counter-trend" in result.reason

    def test_scalp_flat_trend_returns_none(self):
        """No signal when trend is flat."""
        trend = TrendState(direction="flat", ema_fast_value=2050, ema_slow_value=2050, slope=0)
        candles_m1 = _make_candles([(2050, 2051, 2049, 2050)] * 15)
        s5 = _make_candles([(2050, 2050.1, 2049.9, 2050)])
        result = evaluate_scalp_entry(candles_m1, s5, trend)
        assert result is None

    def test_scalp_sell_with_bearish_trend(self):
        """Sell signal when bearish trend + pullback up + bearish engulfing."""
        trend = TrendState(
            direction="bearish", ema_fast_value=2050, ema_slow_value=2060, slope=-10,
        )
        # M1 candles: price rallies back up then shows bearish engulfing
        prices = []
        for i in range(12):
            base = 2048 + i * 0.3
            prices.append((base, base + 0.3, base - 0.2, base + 0.15))
        # At price ~2051.6 area, add bullish then bearish engulfing
        prices.append((2051.0, 2051.5, 2050.8, 2051.3))  # bullish
        prices.append((2051.4, 2051.5, 2050.5, 2050.7))  # bearish engulfing
        candles_m1 = _make_candles(prices)
        s5 = _make_candles([(2051.0, 2051.2, 2050.8, 2050.9)])

        result = evaluate_scalp_entry(candles_m1, s5, trend)
        assert result is not None
        assert result.direction == "sell"


# ── Candlestick Patterns ─────────────────────────────────────────────────


class TestCandlestickPatterns:
    def test_bullish_engulfing(self):
        prev = CandleData("t", 10.0, 10.2, 9.7, 9.8, 100)  # bearish
        curr = CandleData("t", 9.7, 10.5, 9.6, 10.3, 100)  # bullish engulfing
        assert _is_bullish_engulfing(prev, curr) is True

    def test_hammer(self):
        # body small, lower wick >= 2x body, upper wick small
        # open=100.1, close=100.2 → body=0.1, low=99.8 → lower_wick=0.3, high=100.2 → upper_wick=0
        candle = CandleData("t", 100.1, 100.2, 99.8, 100.2, 100)
        assert _is_hammer(candle) is True

    def test_shooting_star(self):
        # body small, upper wick >= 2x body, lower wick small
        # open=100.2, close=100.1 → body=0.1, high=100.5 → upper_wick=0.3, low=100.1 → lower_wick=0
        candle = CandleData("t", 100.2, 100.5, 100.1, 100.1, 100)
        assert _is_shooting_star(candle) is True


# ── Scalp SL/TP ──────────────────────────────────────────────────────────


class TestScalpSLTP:
    def test_scalp_sl_swing_low_buy(self):
        """SL placed at recent swing low for buy."""
        # V-shape: entry 2050.50, swing low at 2050.10 → distance 0.40 = 40 pips
        prices = [
            (2050.50, 2050.60, 2050.40, 2050.50),  # 0
            (2050.45, 2050.55, 2050.30, 2050.35),  # 1
            (2050.35, 2050.40, 2050.20, 2050.25),  # 2
            (2050.25, 2050.30, 2050.15, 2050.18),  # 3
            (2050.18, 2050.22, 2050.12, 2050.14),  # 4
            (2050.14, 2050.20, 2050.10, 2050.12),  # 5 — swing low (low=2050.10)
            (2050.15, 2050.30, 2050.12, 2050.28),  # 6 — recovering
            (2050.28, 2050.40, 2050.25, 2050.38),  # 7
            (2050.38, 2050.50, 2050.35, 2050.48),  # 8
            (2050.48, 2050.58, 2050.45, 2050.55),  # 9
        ]
        candles = _make_candles(prices)
        # entry=2050.55, swing low=2050.10 → ~45 pips distance → within 15-100
        sl = calculate_scalp_sl(
            entry_price=2050.55,
            direction="buy",
            candles_m1=candles,
            pip_value=0.01,
        )
        assert sl is not None
        assert sl < 2050.55  # SL is below entry
        assert sl <= 2050.10  # SL at or below swing low

    def test_scalp_sl_min_bound(self):
        """Trade skipped when SL is too tight (< 15 pips)."""
        # Create candles where swing low is very close to entry
        prices = [(2050, 2050.2, 2050.0, 2050.1)] * 10
        candles = _make_candles(prices)
        sl = calculate_scalp_sl(
            entry_price=2050.1,
            direction="buy",
            candles_m1=candles,
            pip_value=0.01,
        )
        assert sl is None  # Too tight -> skipped

    def test_scalp_sl_max_bound(self):
        """Trade skipped when SL is too wide (> 100 pips)."""
        # Create candles with swing low very far from entry
        prices = [(2050, 2052, 2035, 2036)] * 5 + [(2050, 2060, 2049, 2055)] * 5
        candles = _make_candles(prices)
        sl = calculate_scalp_sl(
            entry_price=2060.0,
            direction="buy",
            candles_m1=candles,
            pip_value=0.01,
        )
        # SL distance = 2060 - ~2034 = 2600 pips >> 100 pips
        assert sl is None

    def test_scalp_tp_rr_buy(self):
        """TP = entry + 1.5 × risk for buy."""
        tp = calculate_scalp_tp(
            entry_price=2050.0,
            direction="buy",
            sl_price=2046.0,
            rr_ratio=1.5,
        )
        expected = 2050.0 + (4.0 * 1.5)
        assert tp == expected

    def test_scalp_tp_rr_sell(self):
        """TP = entry - 1.5 × risk for sell."""
        tp = calculate_scalp_tp(
            entry_price=2050.0,
            direction="sell",
            sl_price=2054.0,
            rr_ratio=1.5,
        )
        expected = 2050.0 - (4.0 * 1.5)
        assert tp == expected


# ── Trailing Stop ────────────────────────────────────────────────────────


class TestTrailingStop:
    def test_trailing_stop_breakeven(self):
        """SL moves to entry price at 1R profit."""
        ts = TrailingStop(entry_price=2050.0, initial_sl=2046.0, direction="buy")
        # At 1R = 4.0 profit → price = 2054.0
        new_sl = ts.update(2054.0)
        assert new_sl == 2050.0  # Breakeven

    def test_trailing_stop_no_change_before_1r(self):
        """SL doesn't move before 1R profit."""
        ts = TrailingStop(entry_price=2050.0, initial_sl=2046.0, direction="buy")
        new_sl = ts.update(2053.0)  # Only 0.75R
        assert new_sl is None

    def test_trailing_stop_trail_at_1_5r(self):
        """SL trails by 0.5R at 1.5R profit."""
        ts = TrailingStop(entry_price=2050.0, initial_sl=2046.0, direction="buy")
        risk = 4.0  # entry - initial_sl
        # First hit breakeven at 1R
        ts.update(2054.0)
        # Now at 1.5R = 6.0 profit → price = 2056.0
        new_sl = ts.update(2056.0)
        # Trail = price - 0.5 * risk = 2056 - 2 = 2054.0
        assert new_sl == 2054.0

    def test_trailing_stop_trail_sell(self):
        """Trailing stop works for sell direction."""
        ts = TrailingStop(entry_price=2050.0, initial_sl=2054.0, direction="sell")
        # At 1R down → price = 2046.0
        new_sl = ts.update(2046.0)
        assert new_sl == 2050.0  # Breakeven

        # At 1.5R → price = 2044.0
        new_sl = ts.update(2044.0)
        # Trail = price + 0.5 * 4 = 2044 + 2 = 2046
        assert new_sl == 2046.0

    def test_trailing_stop_only_tightens(self):
        """SL never moves backward (widen)."""
        ts = TrailingStop(entry_price=2050.0, initial_sl=2046.0, direction="buy")
        ts.update(2054.0)  # breakeven
        ts.update(2058.0)  # trail to 2056
        # Price drops back
        result = ts.update(2054.5)  # Still above entry, but SL should stay
        assert result is None  # No change — SL stays at 2056


# ── Spread Filter ────────────────────────────────────────────────────────


class TestSpreadFilter:
    def test_spread_filter_accept(self):
        """Entry allowed when spread < max."""
        assert is_spread_acceptable(
            bid=2050.0, ask=2050.03, max_spread_pips=4.0, pip_value=0.01,
        ) is True  # spread = 3 pips

    def test_spread_filter_reject(self):
        """Entry blocked when spread > max."""
        assert is_spread_acceptable(
            bid=2050.0, ask=2050.10, max_spread_pips=4.0, pip_value=0.01,
        ) is False  # spread = 10 pips

    def test_spread_filter_exact_boundary(self):
        """Entry allowed at exactly max spread."""
        assert is_spread_acceptable(
            bid=2050.0, ask=2050.04, max_spread_pips=4.0, pip_value=0.01,
        ) is True  # spread = exactly 4 pips


# ── Position Count Guard ─────────────────────────────────────────────────


class TestPositionCountGuard:
    @pytest.mark.asyncio
    async def test_max_positions_guard(self):
        """Engine skips trade when max concurrent positions reached."""
        from app.broker.models import AccountSummary, Position
        from app.config import Config
        from app.engine import TradingEngine
        from app.models.stream_config import StreamConfig
        from datetime import datetime, timezone

        config = Config(
            oanda_account_id="test", oanda_api_token="test",
            oanda_environment="practice", trade_pair="XAU_USD",
            risk_per_trade_pct=0.5, max_drawdown_pct=10.0,
            session_start_utc=0, session_end_utc=23,
            db_path=":memory:", log_level="WARNING", health_port=8080,
        )
        sc = StreamConfig(
            name="scalp-test", instrument="XAU_USD", strategy="trend_scalp",
            timeframes=["H1", "M1"], poll_interval_seconds=60,
            risk_per_trade_pct=0.5, max_concurrent_positions=2,
            session_start_utc=0, session_end_utc=23, enabled=True,
        )

        broker = AsyncMock()
        broker.get_account_summary.return_value = AccountSummary(
            account_id="test", balance=10000.0, equity=10000.0,
            open_position_count=2, currency="USD",
        )
        # 2 existing positions (= max)
        broker.list_open_positions.return_value = [
            Position(instrument="XAU_USD", long_units=1, short_units=0,
                     unrealized_pnl=5, average_price=2050),
            Position(instrument="XAU_USD", long_units=0, short_units=-1,
                     unrealized_pnl=-3, average_price=2060),
        ]

        # Create a mock strategy that always returns a signal
        from app.strategy.base import StrategyResult
        from app.strategy.models import EntrySignal, SRZone
        mock_strategy = AsyncMock()
        mock_strategy.evaluate.return_value = StrategyResult(
            signal=EntrySignal(
                direction="buy", entry_price=2050.0,
                sr_zone=SRZone(zone_type="support", price_level=2045.0, strength=3),
                candle_time="2025-01-01T12:00:00Z", reason="test",
            ),
            sl=2046.0, tp=2056.0, atr=None,
        )

        engine = TradingEngine(config, broker, strategy=mock_strategy,
                               stream_config=sc)
        utc_now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
        result = await engine.run_once(utc_now=utc_now)
        assert result["action"] == "skipped"
        assert result["reason"] == "max_concurrent_positions"


# ── Strategy Registry ───────────────────────────────────────────────────


class TestStrategyRegistryPhase10:
    def test_trend_scalp_in_registry(self):
        from app.strategy.registry import STRATEGY_REGISTRY, get_strategy
        assert "trend_scalp" in STRATEGY_REGISTRY

    def test_get_trend_scalp_strategy(self):
        from app.strategy.registry import get_strategy
        strat = get_strategy("trend_scalp")
        assert isinstance(strat, TrendScalpStrategy)

    def test_trend_scalp_satisfies_protocol(self):
        strat = TrendScalpStrategy()
        assert isinstance(strat, StrategyProtocol)


# ── TrendScalpStrategy Integration ───────────────────────────────────────


class TestTrendScalpStrategyInteg:
    @pytest.mark.asyncio
    async def test_strategy_returns_none_when_flat(self):
        """Strategy returns None when H1 trend is flat."""
        from app.broker.models import Candle

        broker = AsyncMock()
        import math
        flat_candles = [
            Candle(
                time=f"2025-01-01T{i:02d}:00:00Z",
                open=2050.0 + math.sin(i * 0.5) * 2,
                high=2052.0 + math.sin(i * 0.5) * 2,
                low=2048.0 + math.sin(i * 0.5) * 2,
                close=2050.0 + math.sin(i * 0.5) * 1.5,
                volume=100,
                complete=True,
            )
            for i in range(50)
        ]
        broker.fetch_candles.return_value = flat_candles

        config = MagicMock()
        config.trade_pair = "XAU_USD"

        strat = TrendScalpStrategy()
        result = await strat.evaluate(broker, config)
        assert result is None
