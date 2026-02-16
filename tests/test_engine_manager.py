"""Tests for Phase 9 — Multi-Stream Engine Manager.

Verifies:
  - StreamConfig loading from forge.json
  - Strategy registry resolution
  - EngineManager lifecycle (build, run, stop)
  - Per-stream status isolation
  - Trade tagging with stream_name
  - Trade repo stream filtering
  - Router multi-stream status endpoints
  - Backward compatibility (single-stream fallback)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.routers import (
    _stream_statuses,
    configure_routers,
    update_bot_status,
    update_pending_signal,
)
from app.config import Config
from app.engine import TradingEngine
from app.engine_manager import EngineManager
from app.main import app
from app.models.stream_config import StreamConfig
from app.strategy.registry import STRATEGY_REGISTRY, get_strategy
from app.strategy.sr_rejection import SRRejectionStrategy

from fastapi.testclient import TestClient


# ── Helpers ──────────────────────────────────────────────────────────────

client = TestClient(app)


def _make_config(**overrides) -> Config:
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


def _make_stream(name="test-stream", **overrides) -> StreamConfig:
    defaults = dict(
        name=name,
        instrument="EUR_USD",
        strategy="sr_rejection",
        timeframes=["D", "H4"],
        poll_interval_seconds=300,
        risk_per_trade_pct=1.0,
        max_concurrent_positions=1,
        session_start_utc=7,
        session_end_utc=20,
        enabled=True,
    )
    defaults.update(overrides)
    return StreamConfig(**defaults)


def _make_broker():
    return AsyncMock()


def _make_trade_repo(trades=None, total=0):
    repo = MagicMock()
    if trades is None:
        trades = []
    repo.get_trades.return_value = {"trades": trades, "total": total}
    return repo


# ── StreamConfig ─────────────────────────────────────────────────────────


class TestStreamConfig:
    def test_create_stream_config(self):
        sc = _make_stream(name="swing", instrument="GBP_USD")
        assert sc.name == "swing"
        assert sc.instrument == "GBP_USD"
        assert sc.enabled is True

    def test_stream_config_frozen(self):
        sc = _make_stream()
        with pytest.raises(AttributeError):
            sc.name = "other"

    def test_stream_config_disabled(self):
        sc = _make_stream(enabled=False)
        assert sc.enabled is False


# ── Strategy Registry ───────────────────────────────────────────────────


class TestStrategyRegistry:
    def test_sr_rejection_in_registry(self):
        assert "sr_rejection" in STRATEGY_REGISTRY

    def test_get_strategy_returns_instance(self):
        strat = get_strategy("sr_rejection")
        assert isinstance(strat, SRRejectionStrategy)

    def test_get_strategy_unknown_raises(self):
        with pytest.raises(KeyError):
            get_strategy("nonexistent_strategy")


# ── EngineManager ────────────────────────────────────────────────────────


class TestEngineManager:
    def test_build_engines_single_stream(self):
        config = _make_config()
        broker = _make_broker()
        streams = [_make_stream(name="s1")]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        assert "s1" in mgr.engines
        assert len(mgr.stream_names) == 1

    def test_build_engines_multiple_streams(self):
        config = _make_config()
        broker = _make_broker()
        streams = [
            _make_stream(name="s1", instrument="EUR_USD"),
            _make_stream(name="s2", instrument="XAU_USD"),
        ]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        assert set(mgr.stream_names) == {"s1", "s2"}

    def test_disabled_streams_excluded(self):
        config = _make_config()
        broker = _make_broker()
        streams = [
            _make_stream(name="live", enabled=True),
            _make_stream(name="off", enabled=False),
        ]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        assert "live" in mgr.engines
        assert "off" not in mgr.engines

    def test_stop_all(self):
        config = _make_config()
        broker = _make_broker()
        streams = [_make_stream(name="x"), _make_stream(name="y")]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        mgr.stop_all()
        for eng in mgr.engines.values():
            assert eng._running is False

    def test_stop_single_stream(self):
        config = _make_config()
        broker = _make_broker()
        streams = [_make_stream(name="a"), _make_stream(name="b")]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        # Simulate both engines being "running"
        mgr.engines["a"]._running = True
        mgr.engines["b"]._running = True
        mgr.stop_stream("a")
        assert mgr.engines["a"]._running is False
        assert mgr.engines["b"]._running is True

    def test_get_status_single(self):
        config = _make_config()
        broker = _make_broker()
        streams = [_make_stream(name="demo", instrument="GBP_USD")]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        status = mgr.get_status("demo")
        assert status["stream_name"] == "demo"
        assert status["instrument"] == "GBP_USD"

    def test_get_status_unknown_stream(self):
        config = _make_config()
        broker = _make_broker()
        mgr = EngineManager(config, broker, [])
        mgr.build_engines()
        status = mgr.get_status("nope")
        assert "error" in status

    def test_get_status_all(self):
        config = _make_config()
        broker = _make_broker()
        streams = [_make_stream(name="s1"), _make_stream(name="s2")]
        mgr = EngineManager(config, broker, streams)
        mgr.build_engines()
        status = mgr.get_status()
        assert "streams" in status
        assert "s1" in status["streams"]
        assert "s2" in status["streams"]


# ── Engine Stream Properties ─────────────────────────────────────────────


class TestEngineStreamProperties:
    def test_engine_uses_stream_config_instrument(self):
        config = _make_config()
        broker = _make_broker()
        sc = _make_stream(name="gold", instrument="XAU_USD")
        engine = TradingEngine(config, broker, strategy=SRRejectionStrategy(),
                               stream_config=sc)
        assert engine.instrument == "XAU_USD"
        assert engine.stream_name == "gold"

    def test_engine_fallback_no_stream_config(self):
        config = _make_config(trade_pair="GBP_USD")
        broker = _make_broker()
        engine = TradingEngine(config, broker, strategy=SRRejectionStrategy())
        assert engine.instrument == "GBP_USD"
        assert engine.stream_name == "default"

    def test_engine_session_from_stream(self):
        config = _make_config()
        broker = _make_broker()
        sc = _make_stream(session_start_utc=10, session_end_utc=18)
        engine = TradingEngine(config, broker, strategy=SRRejectionStrategy(),
                               stream_config=sc)
        assert engine._session_start == 10
        assert engine._session_end == 18

    def test_engine_risk_from_stream(self):
        config = _make_config(risk_per_trade_pct=2.0)
        broker = _make_broker()
        sc = _make_stream(risk_per_trade_pct=0.5)
        engine = TradingEngine(config, broker, strategy=SRRejectionStrategy(),
                               stream_config=sc)
        assert engine._risk_pct == 0.5


# ── Router Multi-Stream Status ───────────────────────────────────────────


class TestRouterMultiStream:
    def setup_method(self):
        """Reset stream statuses between tests."""
        _stream_statuses.clear()
        _stream_statuses["default"] = {
            "mode": "idle",
            "running": False,
            "stream_name": "default",
        }

    def test_update_bot_status_creates_stream(self):
        update_bot_status(stream_name="gold-scalp", running=True)
        assert "gold-scalp" in _stream_statuses
        assert _stream_statuses["gold-scalp"]["running"] is True

    def test_update_bot_status_default_stream(self):
        update_bot_status(cycle_count=5)
        assert _stream_statuses["default"]["cycle_count"] == 5

    def test_status_endpoint_returns_all_streams(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_bot_status(stream_name="s1", running=True)
        update_bot_status(stream_name="s2", running=False)
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "streams" in data
        assert "s1" in data["streams"]
        assert "s2" in data["streams"]

    def test_status_stream_endpoint(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_bot_status(stream_name="my-stream", pair="XAU_USD", running=True)
        resp = client.get("/status/my-stream")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pair"] == "XAU_USD"
        assert data["running"] is True

    def test_status_unknown_stream(self):
        configure_routers(trade_repo=_make_trade_repo())
        resp = client.get("/status/nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data


# ── Trade Repo Stream Filtering ──────────────────────────────────────────


class TestTradeRepoStream:
    def test_insert_trade_with_stream_name(self, tmp_path):
        from app.repos.db import init_db
        from app.repos.trade_repo import TradeRepo

        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        repo = TradeRepo(db_path)
        tid = repo.insert_trade(
            mode="paper",
            direction="buy",
            pair="EUR_USD",
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            units=1000,
            sr_zone_price=1.0970,
            sr_zone_type="support",
            entry_reason="test",
            opened_at="2025-01-01T00:00:00Z",
            stream_name="swing",
        )
        assert tid > 0

    def test_get_trades_filter_by_stream(self, tmp_path):
        from app.repos.db import init_db
        from app.repos.trade_repo import TradeRepo

        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        repo = TradeRepo(db_path)

        # Insert 2 trades in different streams
        repo.insert_trade(
            mode="paper", direction="buy", pair="EUR_USD",
            entry_price=1.1, stop_loss=1.09, take_profit=1.12,
            units=100, sr_zone_price=1.095, sr_zone_type="support",
            entry_reason="test", opened_at="2025-01-01T00:00:00Z",
            stream_name="stream-a",
        )
        repo.insert_trade(
            mode="paper", direction="sell", pair="XAU_USD",
            entry_price=2000, stop_loss=2010, take_profit=1980,
            units=1, sr_zone_price=2005, sr_zone_type="resistance",
            entry_reason="test", opened_at="2025-01-01T01:00:00Z",
            stream_name="stream-b",
        )

        result_a = repo.get_trades(stream_name="stream-a")
        assert result_a["total"] == 1
        assert result_a["trades"][0]["pair"] == "EUR_USD"

        result_b = repo.get_trades(stream_name="stream-b")
        assert result_b["total"] == 1
        assert result_b["trades"][0]["pair"] == "XAU_USD"

        result_all = repo.get_trades()
        assert result_all["total"] == 2


# ── Config load_streams ──────────────────────────────────────────────────


class TestLoadStreams:
    def test_load_streams_from_forge_json(self, tmp_path):
        import json

        forge = tmp_path / "forge.json"
        forge.write_text(json.dumps({
            "streams": [
                {
                    "name": "s1",
                    "instrument": "EUR_USD",
                    "strategy": "sr_rejection",
                    "timeframes": ["D", "H4"],
                    "poll_interval_seconds": 60,
                    "risk_per_trade_pct": 1.0,
                    "max_concurrent_positions": 1,
                    "session_start_utc": 7,
                    "session_end_utc": 20,
                    "enabled": True,
                }
            ]
        }))

        from app.config import load_streams
        with patch("app.config._FORGE_JSON", forge):
            streams = load_streams()
        assert len(streams) == 1
        assert streams[0].name == "s1"
        assert streams[0].instrument == "EUR_USD"

    def test_load_streams_fallback_no_file(self, tmp_path, monkeypatch):
        """When forge.json has no streams, falls back to env-var config."""
        monkeypatch.setenv("TRADE_PAIR", "GBP_USD")
        monkeypatch.setenv("SESSION_START_UTC", "8")
        monkeypatch.setenv("SESSION_END_UTC", "19")
        monkeypatch.setenv("RISK_PER_TRADE_PCT", "2.0")

        nonexistent = tmp_path / "nope.json"

        from app.config import load_streams
        with patch("app.config._FORGE_JSON", nonexistent):
            streams = load_streams()
        assert len(streams) == 1
        assert streams[0].name == "default"
        assert streams[0].instrument == "GBP_USD"
