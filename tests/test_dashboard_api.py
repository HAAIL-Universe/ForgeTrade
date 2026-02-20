"""Tests for Phase 7 — Dashboard API endpoints and static serving."""

from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.api.routers import configure_routers, update_bot_status, update_pending_signal
from app.main import app

client = TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_trade_repo(trades=None, total=0):
    """Return a mock TradeRepo with canned get_trades response."""
    repo = MagicMock()
    if trades is None:
        trades = []
    repo.get_trades.return_value = {"trades": trades, "total": total}
    return repo


def _make_broker(positions=None, trades=None):
    """Return a mock broker with canned list_open_positions/trades response."""
    broker = AsyncMock()
    if positions is None:
        positions = []
    if trades is None:
        trades = []
    broker.list_open_positions.return_value = positions
    broker.list_open_trades.return_value = trades
    return broker


# ── Tests ────────────────────────────────────────────────────────────────


class TestPositionsEndpoint:
    def test_positions_returns_200_empty(self):
        broker = _make_broker(positions=[])
        configure_routers(trade_repo=_make_trade_repo(), broker=broker)
        resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert "positions" in data
        assert isinstance(data["positions"], list)

    def test_positions_returns_list_schema(self):
        from app.broker.models import Trade

        trades = [
            Trade(
                trade_id="123",
                instrument="EUR_USD",
                units=1000.0,
                price=1.08500,
                unrealized_pnl=25.50,
                stop_loss_price=1.07500,
                take_profit_price=1.09500,
                open_time="2026-02-17T14:51:19Z",
            )
        ]
        broker = _make_broker(trades=trades)
        configure_routers(trade_repo=_make_trade_repo(), broker=broker)
        resp = client.get("/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["positions"]) == 1
        pos = data["positions"][0]
        assert pos["instrument"] == "EUR_USD"
        assert pos["direction"] == "long"
        assert pos["units"] == 1000.0
        assert pos["avg_price"] == 1.08500
        assert pos["unrealized_pnl"] == 25.50
        assert pos["stop_loss"] == 1.07500
        assert pos["take_profit"] == 1.09500

    def test_positions_no_broker(self):
        configure_routers(trade_repo=_make_trade_repo(), broker=None)
        resp = client.get("/positions")
        assert resp.status_code == 200
        assert resp.json() == {"positions": []}


class TestPendingSignalsEndpoint:
    def test_pending_signals_returns_200(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_pending_signal(None)
        resp = client.get("/signals/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert "signal" in data

    def test_pending_signals_returns_null_when_none(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_pending_signal(None)
        resp = client.get("/signals/pending")
        assert resp.json()["signal"] is None

    def test_pending_signals_returns_signal_shape(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_pending_signal({
            "pair": "EUR_USD",
            "direction": "buy",
            "zone_price": 1.08200,
            "zone_type": "support",
            "reason": "Rejection wick at support",
            "status": "watching",
            "evaluated_at": "2025-01-01T12:00:00+00:00",
            "stream_name": "default",
        })
        resp = client.get("/signals/pending")
        sig = resp.json()["signal"]
        assert sig is not None
        assert sig["pair"] == "EUR_USD"
        assert sig["direction"] == "buy"
        assert sig["status"] == "watching"


class TestClosedTradesEndpoint:
    def test_closed_trades_returns_200(self):
        configure_routers(trade_repo=_make_trade_repo())
        resp = client.get("/trades/closed")
        assert resp.status_code == 200
        data = resp.json()
        assert "trades" in data
        assert "total_pnl" in data

    def test_closed_trades_returns_pnl(self):
        trades = [
            {"pnl": 25.0, "status": "closed"},
            {"pnl": -10.0, "status": "closed"},
        ]
        repo = _make_trade_repo(trades=trades, total=2)
        configure_routers(trade_repo=repo)
        resp = client.get("/trades/closed")
        data = resp.json()
        assert data["total_pnl"] == 15.0

    def test_closed_trades_calls_repo_with_closed_filter(self):
        repo = _make_trade_repo()
        configure_routers(trade_repo=repo)
        client.get("/trades/closed?limit=10")
        repo.get_trades.assert_called_with(
            limit=10, status_filter="closed", stream_name=None,
        )


class TestStatusEnriched:
    def test_status_includes_cycle_count(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_bot_status(stream_name="default", cycle_count=42,
                          last_cycle_at="2025-01-01T12:00:00+00:00")
        resp = client.get("/status/default")
        data = resp.json()
        assert data["cycle_count"] == 42
        assert data["last_cycle_at"] == "2025-01-01T12:00:00+00:00"

    def test_status_includes_stream_name(self):
        configure_routers(trade_repo=_make_trade_repo())
        update_bot_status(stream_name="sr-swing")
        resp = client.get("/status")
        data = resp.json()
        assert "streams" in data
        assert "sr-swing" in data["streams"]


class TestDashboardServed:
    def test_dashboard_serves_html(self):
        resp = client.get("/dashboard/index.html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_root_serves_dashboard(self):
        """Root serves the Vite build (200) or redirects to legacy (307)."""
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (200, 307)
        if resp.status_code == 307:
            assert "/dashboard/index.html" in resp.headers.get("location", "")
