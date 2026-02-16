"""Tests for Phase 6 — Paper & Live Integration.

Covers live-mode warning, graceful shutdown, error resilience,
and paper/live logic equivalence.
"""

import logging
from datetime import datetime, timezone

import pytest

from app.broker.models import AccountSummary, Candle, OrderResponse
from app.config import Config
from app.engine import TradingEngine
from app.main import warn_if_live
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


class MockBroker:
    """Duck-typed broker for integration tests."""

    def __init__(self, daily, h4, equity=10_000.0):
        self._daily = daily
        self._h4 = h4
        self._equity = equity
        self.placed_orders = []

    async def fetch_candles(self, instrument, granularity, count=50):
        if granularity == "D":
            return self._daily
        return self._h4

    async def get_account_summary(self):
        return AccountSummary("test", self._equity, self._equity, 0, "USD")

    async def place_order(self, order_req):
        self.placed_orders.append(order_req)
        return OrderResponse("99", order_req.instrument, order_req.units, 1.083, "2025-02-01T08:00:00Z")


# ── Tests ────────────────────────────────────────────────────────────────


class TestLiveModeWarning:

    def test_live_mode_warning(self, caplog):
        """Warning message logged when mode=live."""
        with caplog.at_level(logging.WARNING, logger="forgetrade"):
            result = warn_if_live("live")
        assert result is True
        assert "LIVE TRADING MODE" in caplog.text

    def test_no_warning_paper(self, caplog):
        """No warning when mode=paper."""
        with caplog.at_level(logging.WARNING, logger="forgetrade"):
            result = warn_if_live("paper")
        assert result is False
        assert "LIVE TRADING MODE" not in caplog.text


class TestGracefulShutdown:

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self):
        """Shutdown handler stops the engine loop."""
        config = _make_config()
        broker = MockBroker(_daily_candles(), _h4_buy_candles())
        strategy = SRRejectionStrategy()
        engine = TradingEngine(config=config, broker=broker, strategy=strategy)
        await engine.initialize()

        # Stop immediately before entering the loop
        engine.stop()
        results = await engine.run(poll_interval=0, max_cycles=0)

        # Engine should have exited the loop without processing any cycle
        assert results == []
        assert engine._running is False


class TestErrorResilience:

    @pytest.mark.asyncio
    async def test_api_error_retry(self):
        """Bot continues after a transient broker error."""
        daily = _daily_candles()
        h4 = _h4_buy_candles()
        good_broker = MockBroker(daily, h4)

        class ErrorOnceBroker:
            """Raises on the first fetch_candles call, then delegates."""

            def __init__(self, inner):
                self._inner = inner
                self._calls = 0

            async def fetch_candles(self, *a, **kw):
                self._calls += 1
                if self._calls <= 1:
                    raise ConnectionError("OANDA timeout")
                return await self._inner.fetch_candles(*a, **kw)

            async def get_account_summary(self):
                return await self._inner.get_account_summary()

            async def place_order(self, req):
                return await self._inner.place_order(req)

        config = _make_config()
        broker = ErrorOnceBroker(good_broker)
        strategy = SRRejectionStrategy()
        engine = TradingEngine(config=config, broker=broker, strategy=strategy)
        await engine.initialize()

        utc_now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        results = await engine.run(poll_interval=0, max_cycles=2)

        # First cycle should have errored
        assert results[0]["action"] == "error"
        # Second cycle should have succeeded (order placed or signal evaluated)
        assert results[1]["action"] in ("order_placed", "skipped")


class TestPaperLiveSameLogic:

    @pytest.mark.asyncio
    async def test_paper_live_same_logic(self):
        """Same candle data produces same signal regardless of mode."""
        daily = _daily_candles()
        h4 = _h4_buy_candles()
        utc_now = datetime(2025, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

        config_paper = _make_config(oanda_environment="practice")
        config_live = _make_config(oanda_environment="live")

        broker_p = MockBroker(daily, h4)
        broker_l = MockBroker(daily, h4)

        strategy_p = SRRejectionStrategy()
        strategy_l = SRRejectionStrategy()
        engine_p = TradingEngine(config=config_paper, broker=broker_p, strategy=strategy_p)
        engine_l = TradingEngine(config=config_live, broker=broker_l, strategy=strategy_l)

        await engine_p.initialize()
        await engine_l.initialize()

        result_p = await engine_p.run_once(utc_now=utc_now)
        result_l = await engine_l.run_once(utc_now=utc_now)

        assert result_p["action"] == result_l["action"]
        assert result_p["direction"] == result_l["direction"]
        assert result_p["units"] == result_l["units"]
