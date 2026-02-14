"""Tests for the trading engine orchestration.

Verifies end-to-end flow: fetch candles → evaluate signal → risk → order.
Uses a mock broker to avoid real OANDA calls.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from app.broker.models import AccountSummary, Candle, OrderResponse
from app.config import Config
from app.engine import TradingEngine
from app.strategy.models import CandleData


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_config(**overrides) -> Config:
    """Build a Config with sensible test defaults."""
    defaults = dict(
        oanda_account_id="101-001-XXXXX-001",
        oanda_api_token="test_token",
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


def _daily_candles_for_engine() -> list[Candle]:
    """50 daily Candle objects producing clear S/R zones.

    Same oscillating pattern as test_strategy.py but using broker Candle type.
    """
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
    candles: list[Candle] = []
    spread = 0.0020
    for i, base in enumerate(base_prices):
        candles.append(
            Candle(
                time=f"2025-01-{i + 1:02d}T00:00:00Z",
                open=base,
                high=base + spread,
                low=base - spread,
                close=base,
                volume=1000,
                complete=True,
            )
        )
    return candles


def _h4_candles_buy_signal() -> list[Candle]:
    """4H candles with a buy signal at support ~1.0800."""
    return [
        Candle("2025-02-01T00:00:00Z", 1.0850, 1.0860, 1.0840, 1.0845, 1000, True),
        Candle("2025-02-01T04:00:00Z", 1.0845, 1.0850, 1.0830, 1.0835, 1000, True),
        Candle("2025-02-01T08:00:00Z", 1.0820, 1.0835, 1.0795, 1.0830, 1000, True),
    ]


def _h4_candles_no_signal() -> list[Candle]:
    """4H candles that do NOT touch any zone — no signal."""
    return [
        Candle("2025-02-01T08:00:00Z", 1.0900, 1.0920, 1.0890, 1.0910, 1000, True),
    ]


# ── Mock broker ──────────────────────────────────────────────────────────


class MockBroker:
    """Duck-typed OandaClient replacement for engine tests."""

    def __init__(
        self,
        daily_candles: list[Candle],
        h4_candles: list[Candle],
        equity: float = 10_000.0,
    ) -> None:
        self._daily = daily_candles
        self._h4 = h4_candles
        self._equity = equity
        self.placed_orders: list = []

    async def fetch_candles(self, instrument: str, granularity: str, count: int = 50):
        if granularity == "D":
            return self._daily
        return self._h4

    async def get_account_summary(self):
        return AccountSummary(
            account_id="101-001-XXXXX-001",
            balance=self._equity,
            equity=self._equity,
            open_position_count=0,
            currency="USD",
        )

    async def place_order(self, order_req):
        self.placed_orders.append(order_req)
        return OrderResponse(
            order_id="12345",
            instrument=order_req.instrument,
            units=order_req.units,
            price=1.0830,
            time="2025-02-01T08:00:00Z",
        )


# ── Engine tests ─────────────────────────────────────────────────────────


class TestTradingEngine:
    """Integration tests for TradingEngine.run_once()."""

    @pytest.mark.asyncio
    async def test_engine_places_order_end_to_end(self):
        """Full cycle: fetch → evaluate → risk → order placed."""
        config = _make_config()
        broker = MockBroker(
            daily_candles=_daily_candles_for_engine(),
            h4_candles=_h4_candles_buy_signal(),
        )
        engine = TradingEngine(config=config, broker=broker)
        await engine.initialize()

        # 12:00 UTC = within session
        utc_now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = await engine.run_once(utc_now=utc_now)

        assert result["action"] == "order_placed"
        assert result["direction"] == "buy"
        assert result["units"] > 0
        assert result["sl"] < result["entry"]
        assert result["tp"] > result["entry"]
        assert len(broker.placed_orders) == 1

    @pytest.mark.asyncio
    async def test_engine_skips_outside_session(self):
        """Engine skips evaluation outside London+NY session."""
        config = _make_config()
        broker = MockBroker(
            daily_candles=_daily_candles_for_engine(),
            h4_candles=_h4_candles_buy_signal(),
        )
        engine = TradingEngine(config=config, broker=broker)
        await engine.initialize()

        # 03:00 UTC = outside session
        utc_now = datetime(2025, 2, 1, 3, 0, 0, tzinfo=timezone.utc)
        result = await engine.run_once(utc_now=utc_now)

        assert result["action"] == "skipped"
        assert result["reason"] == "outside_session"
        assert len(broker.placed_orders) == 0

    @pytest.mark.asyncio
    async def test_engine_skips_no_signal(self):
        """Engine skips when no signal is produced."""
        config = _make_config()
        broker = MockBroker(
            daily_candles=_daily_candles_for_engine(),
            h4_candles=_h4_candles_no_signal(),
        )
        engine = TradingEngine(config=config, broker=broker)
        await engine.initialize()

        utc_now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = await engine.run_once(utc_now=utc_now)

        assert result["action"] == "skipped"
        assert result["reason"] == "no_signal"

    @pytest.mark.asyncio
    async def test_engine_halts_on_circuit_breaker(self):
        """Engine halts when drawdown exceeds threshold."""
        config = _make_config(max_drawdown_pct=10.0)
        # Equity already below threshold
        broker = MockBroker(
            daily_candles=_daily_candles_for_engine(),
            h4_candles=_h4_candles_buy_signal(),
            equity=10_000.0,
        )
        engine = TradingEngine(config=config, broker=broker)
        await engine.initialize()

        # Simulate drawdown by updating tracker directly
        engine._drawdown.update(8_500.0)  # 15% drawdown

        utc_now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = await engine.run_once(utc_now=utc_now)

        assert result["action"] == "halted"
        assert result["reason"] == "circuit_breaker"
        assert len(broker.placed_orders) == 0
