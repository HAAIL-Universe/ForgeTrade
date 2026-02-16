"""Tests for Phase 4 — Trade Logging, CLI Dashboard, and API endpoints.

Uses in-memory SQLite for repo tests and FastAPI TestClient for API tests.
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repos.db import init_db, get_connection
from app.repos.trade_repo import TradeRepo
from app.repos.equity_repo import EquityRepo
from app.api.routers import configure_routers, update_bot_status
from app.cli.dashboard import print_status


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_db(tmp_path):
    """Create and initialise an in-memory-like SQLite DB in a temp dir."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    return db_path


# ── DB initialisation ───────────────────────────────────────────────────


class TestDBInit:

    def test_db_init_creates_tables(self, tmp_db):
        conn = get_connection(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        conn.close()
        assert "trades" in table_names
        assert "equity_snapshots" in table_names
        assert "sr_zones" in table_names
        assert "backtest_runs" in table_names

    def test_db_init_idempotent(self, tmp_db):
        """Running init twice does not error or duplicate tables."""
        init_db(tmp_db)  # called once by fixture, call again
        conn = get_connection(tmp_db)
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='trades'"
        ).fetchone()[0]
        conn.close()
        assert count == 1


# ── Trade repo ───────────────────────────────────────────────────────────


class TestTradeRepo:

    def test_insert_trade(self, tmp_db):
        repo = TradeRepo(tmp_db)
        trade_id = repo.insert_trade(
            mode="paper",
            direction="buy",
            pair="EUR_USD",
            entry_price=1.08300,
            stop_loss=1.07700,
            take_profit=1.09500,
            units=33333.0,
            sr_zone_price=1.08000,
            sr_zone_type="support",
            entry_reason="Bullish rejection wick at support",
            opened_at="2025-02-01T08:00:00Z",
        )
        assert trade_id >= 1

        result = repo.get_trades(limit=10)
        assert result["total"] == 1
        assert result["trades"][0]["direction"] == "buy"
        assert result["trades"][0]["status"] == "open"

    def test_close_trade(self, tmp_db):
        repo = TradeRepo(tmp_db)
        trade_id = repo.insert_trade(
            mode="paper",
            direction="sell",
            pair="EUR_USD",
            entry_price=1.09800,
            stop_loss=1.10300,
            take_profit=1.09200,
            units=20000.0,
            sr_zone_price=1.10000,
            sr_zone_type="resistance",
            entry_reason="Bearish rejection wick at resistance",
            opened_at="2025-02-01T12:00:00Z",
        )
        repo.close_trade(
            trade_id=trade_id,
            exit_price=1.09200,
            exit_reason="TP hit",
            pnl=120.0,
        )
        result = repo.get_trades(limit=10)
        trade = result["trades"][0]
        assert trade["status"] == "closed"
        assert trade["exit_price"] == 1.09200
        assert trade["pnl"] == 120.0
        assert trade["closed_at"] is not None

    def test_get_trades_filter_status(self, tmp_db):
        repo = TradeRepo(tmp_db)
        repo.insert_trade(
            mode="paper", direction="buy", pair="EUR_USD",
            entry_price=1.0830, stop_loss=1.0770, take_profit=1.0950,
            units=10000.0, sr_zone_price=1.0800, sr_zone_type="support",
            entry_reason="test", opened_at="2025-01-01T00:00:00Z",
        )
        result = repo.get_trades(limit=10, status_filter="closed")
        assert result["total"] == 0
        assert result["trades"] == []


# ── Equity repo ──────────────────────────────────────────────────────────


class TestEquityRepo:

    def test_equity_snapshot(self, tmp_db):
        repo = EquityRepo(tmp_db)
        repo.insert_snapshot(
            mode="paper",
            equity=10000.0,
            balance=10000.0,
            peak_equity=10000.0,
            drawdown_pct=0.0,
            open_positions=0,
        )
        latest = repo.get_latest()
        assert latest is not None
        assert latest["equity"] == 10000.0
        assert latest["mode"] == "paper"

    def test_equity_latest_returns_most_recent(self, tmp_db):
        repo = EquityRepo(tmp_db)
        repo.insert_snapshot("paper", 10000.0, 10000.0, 10000.0, 0.0, 0)
        repo.insert_snapshot("paper", 9500.0, 9500.0, 10000.0, 5.0, 1)
        latest = repo.get_latest()
        assert latest["equity"] == 9500.0
        assert latest["drawdown_pct"] == 5.0


# ── API endpoints ────────────────────────────────────────────────────────


class TestAPIEndpoints:

    def test_status_endpoint(self):
        """GET /status returns 200 with expected schema."""
        update_bot_status(
            stream_name="default",
            mode="paper", running=True, pair="EUR_USD",
            equity=10000.0, balance=10000.0, peak_equity=10000.0,
            drawdown_pct=0.0, circuit_breaker_active=False,
            open_positions=0, last_signal_check=None, uptime_seconds=120,
        )
        client = TestClient(app)
        response = client.get("/status/default")
        assert response.status_code == 200
        data = response.json()
        assert data["mode"] == "paper"
        assert data["running"] is True
        assert data["equity"] == 10000.0
        assert "circuit_breaker_active" in data
        assert "uptime_seconds" in data

    def test_trades_endpoint(self, tmp_db):
        """GET /trades returns 200 with trade list."""
        repo = TradeRepo(tmp_db)
        repo.insert_trade(
            mode="paper", direction="buy", pair="EUR_USD",
            entry_price=1.0830, stop_loss=1.0770, take_profit=1.0950,
            units=33333.0, sr_zone_price=1.0800, sr_zone_type="support",
            entry_reason="test signal", opened_at="2025-02-01T08:00:00Z",
        )
        configure_routers(trade_repo=repo)
        client = TestClient(app)
        response = client.get("/trades")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert len(data["trades"]) == 1
        assert data["trades"][0]["direction"] == "buy"


# ── CLI dashboard ────────────────────────────────────────────────────────


class TestDashboard:

    def test_print_status_format(self, capsys):
        """Dashboard prints formatted status with key fields."""
        status = {
            "mode": "paper",
            "running": True,
            "pair": "EUR_USD",
            "equity": 9850.50,
            "balance": 10000.00,
            "drawdown_pct": 1.5,
            "circuit_breaker_active": False,
            "open_positions": 1,
            "uptime_seconds": 3600,
        }
        output = print_status(status)
        assert "paper" in output
        assert "$9,850.50" in output
        assert "1.50%" in output
        assert "1" in output  # open positions
