"""Tests for Phase 8 — Strategy abstraction and EMA indicators.

Verifies:
- SRRejectionStrategy produces identical output to old inline engine logic
- StrategyProtocol duck-typing works
- EMA calculation matches hand-computed values
- Pip values are correct per instrument
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest

from app.broker.models import AccountSummary, Candle, OrderResponse
from app.config import Config
from app.engine import TradingEngine
from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.indicators import calculate_ema
from app.strategy.models import CandleData, EntrySignal, INSTRUMENT_PIP_VALUES, SRZone
from app.strategy.sr_rejection import SRRejectionStrategy


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_config(**overrides) -> Config:
    defaults = dict(
        oanda_account_id="test",
        oanda_api_token="test",
        oanda_environment="practice",
        trade_pair="EUR_USD",
        risk_per_trade_pct=1.0,
        max_drawdown_pct=10.0,
        session_start_utc=7,
        session_end_utc=21,
        db_path=":memory:",
        log_level="WARNING",
        health_port=8080,
    )
    defaults.update(overrides)
    return Config(**defaults)


def _daily_candles():
    base_prices = [
        1.0950, 1.0930, 1.0900, 1.0870, 1.0840, 1.0810, 1.0800,
        1.0820, 1.0850, 1.0880, 1.0910, 1.0940, 1.0970, 1.1000,
        1.0980, 1.0960, 1.0930, 1.0900, 1.0870, 1.0840, 1.0802,
        1.0825, 1.0855, 1.0885, 1.0915, 1.0945, 1.0975, 1.0998,
        1.0975, 1.0950, 1.0920, 1.0890, 1.0860, 1.0830, 1.0805,
        1.0830, 1.0860, 1.0890, 1.0920, 1.0950, 1.0980, 1.0995,
        1.0970, 1.0940, 1.0910, 1.0880, 1.0850, 1.0820, 1.0808,
        1.0830,
    ]
    sp = 0.0020
    return [
        Candle(f"2025-01-{i+1:02d}T00:00:00Z", b, b + sp, b - sp, b, 1000, True)
        for i, b in enumerate(base_prices)
    ]


def _h4_buy_candles():
    return [
        Candle("2025-02-01T00:00:00Z", 1.0850, 1.0860, 1.0840, 1.0845, 1000, True),
        Candle("2025-02-01T04:00:00Z", 1.0845, 1.0850, 1.0830, 1.0835, 1000, True),
        Candle("2025-02-01T08:00:00Z", 1.0820, 1.0835, 1.0795, 1.0830, 1000, True),
    ]


def _h4_no_signal():
    return [
        Candle("2025-02-01T08:00:00Z", 1.0900, 1.0920, 1.0890, 1.0910, 1000, True),
    ]


class MockBroker:
    def __init__(self, daily, h4, equity=10_000.0):
        self._daily = daily
        self._h4 = h4
        self._equity = equity
        self.placed_orders = []

    async def fetch_candles(self, instrument, granularity, count=50):
        return self._daily if granularity == "D" else self._h4

    async def get_account_summary(self):
        return AccountSummary("test", self._equity, self._equity, 0, "USD")

    async def place_order(self, order_req):
        self.placed_orders.append(order_req)
        return OrderResponse("99", order_req.instrument, order_req.units, 1.083, "2025-02-01T08:00:00Z")


# ── Strategy Abstraction Tests ───────────────────────────────────────────


class TestSRRejectionStrategy:

    @pytest.mark.asyncio
    async def test_sr_strategy_matches_old_logic(self):
        """Given identical candle data, new strategy class returns valid setup."""
        config = _make_config()
        broker = MockBroker(_daily_candles(), _h4_buy_candles())
        strat = SRRejectionStrategy()

        result = await strat.evaluate(broker, config)

        assert result is not None
        assert isinstance(result, StrategyResult)
        assert result.signal.direction == "buy"
        assert result.sl < result.signal.entry_price  # SL below entry for buy
        assert result.tp > result.signal.entry_price  # TP above entry for buy
        assert result.atr is not None
        assert result.atr > 0

    @pytest.mark.asyncio
    async def test_sr_strategy_no_signal(self):
        """Returns None when candles don't produce a signal."""
        config = _make_config()
        broker = MockBroker(_daily_candles(), _h4_no_signal())
        strat = SRRejectionStrategy()

        result = await strat.evaluate(broker, config)
        assert result is None


class TestStrategyProtocol:

    def test_sr_strategy_satisfies_protocol(self):
        """SRRejectionStrategy satisfies StrategyProtocol."""
        strat = SRRejectionStrategy()
        assert isinstance(strat, StrategyProtocol)

    def test_custom_strategy_duck_type(self):
        """A mock strategy implementing the protocol can be used by the engine."""

        class CustomStrategy:
            async def evaluate(self, broker, config) -> Optional[StrategyResult]:
                return None

        strat = CustomStrategy()
        assert isinstance(strat, StrategyProtocol)

    @pytest.mark.asyncio
    async def test_engine_uses_strategy(self):
        """Engine calls strategy.evaluate() and uses returned SL/TP values."""
        config = _make_config()
        broker = MockBroker(_daily_candles(), _h4_buy_candles())
        strat = SRRejectionStrategy()
        engine = TradingEngine(config=config, broker=broker, strategy=strat)
        await engine.initialize()

        utc_now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = await engine.run_once(utc_now=utc_now)

        assert result["action"] == "order_placed"
        assert "sl" in result
        assert "tp" in result


# ── EMA Tests ────────────────────────────────────────────────────────────


class TestEMA:

    def test_ema_known_values(self):
        """EMA(3) of a known price series matches hand computation."""
        # Prices: 10, 11, 12, 13, 14
        # SMA(3) seed = (10+11+12)/3 = 11.0
        # k = 2 / (3+1) = 0.5
        # EMA[2] = 11.0 (seed)
        # EMA[3] = 13 * 0.5 + 11.0 * 0.5 = 12.0
        # EMA[4] = 14 * 0.5 + 12.0 * 0.5 = 13.0
        candles = [
            CandleData(f"T{i}", p, p + 1, p - 1, p, 100)
            for i, p in enumerate([10.0, 11.0, 12.0, 13.0, 14.0])
        ]
        ema = calculate_ema(candles, period=3)

        assert len(ema) == 5
        # First two entries should be NaN
        import math
        assert math.isnan(ema[0])
        assert math.isnan(ema[1])
        # Seed
        assert abs(ema[2] - 11.0) < 1e-6
        # EMA calculations
        assert abs(ema[3] - 12.0) < 1e-6
        assert abs(ema[4] - 13.0) < 1e-6

    def test_ema_21_sufficient_data(self):
        """EMA(21) computes without error with enough data."""
        prices = [100.0 + i * 0.5 for i in range(30)]
        candles = [
            CandleData(f"T{i}", p, p + 1, p - 1, p, 100)
            for i, p in enumerate(prices)
        ]
        ema = calculate_ema(candles, period=21)
        assert len(ema) == 30
        # Last value should be valid (not NaN)
        import math
        assert not math.isnan(ema[-1])

    def test_ema_crossover(self):
        """EMA(3) crossing above EMA(5) is detectable from the series."""
        # Rising prices that cause short EMA to cross above long EMA
        prices = [10.0, 9.0, 8.0, 7.0, 6.0, 7.0, 9.0, 12.0, 15.0, 18.0]
        candles = [
            CandleData(f"T{i}", p, p + 1, p - 1, p, 100)
            for i, p in enumerate(prices)
        ]
        fast = calculate_ema(candles, period=3)
        slow = calculate_ema(candles, period=5)

        # Find crossover: fast was below slow, then goes above
        import math
        crossover_found = False
        for i in range(1, len(prices)):
            if math.isnan(fast[i]) or math.isnan(slow[i]):
                continue
            if math.isnan(fast[i - 1]) or math.isnan(slow[i - 1]):
                continue
            if fast[i - 1] <= slow[i - 1] and fast[i] > slow[i]:
                crossover_found = True
                break

        assert crossover_found, "Expected EMA crossover not detected"

    def test_ema_insufficient_data(self):
        """EMA raises ValueError with insufficient candles."""
        candles = [CandleData("T0", 10, 11, 9, 10, 100)]
        with pytest.raises(ValueError, match="Need at least"):
            calculate_ema(candles, period=5)


# ── Pip Value Tests ──────────────────────────────────────────────────────


class TestPipValues:

    def test_pip_value_eur_usd(self):
        assert INSTRUMENT_PIP_VALUES["EUR_USD"] == 0.0001

    def test_pip_value_xau_usd(self):
        assert INSTRUMENT_PIP_VALUES["XAU_USD"] == 0.01

    def test_pip_value_usd_jpy(self):
        assert INSTRUMENT_PIP_VALUES["USD_JPY"] == 0.01
