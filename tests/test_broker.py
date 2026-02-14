"""Tests for app.broker — OANDA client with mocked HTTP responses."""

import json

import pytest
import httpx

from app.broker.models import Candle, AccountSummary, OrderRequest, OrderResponse, Position
from app.broker.oanda_client import OandaClient
from app.config import Config


def _make_config(environment: str = "practice") -> Config:
    return Config(
        oanda_account_id="101-001-12345678-001",
        oanda_api_token="test-token",
        oanda_environment=environment,
        trade_pair="EUR_USD",
        risk_per_trade_pct=1.0,
        max_drawdown_pct=10.0,
        session_start_utc=7,
        session_end_utc=21,
        db_path="data/forgetrade.db",
        log_level="INFO",
        health_port=8080,
    )


# ── Mock OANDA responses ────────────────────────────────────────────────

MOCK_CANDLES_RESPONSE = {
    "instrument": "EUR_USD",
    "granularity": "D",
    "candles": [
        {
            "complete": True,
            "volume": 12345,
            "time": "2025-01-10T00:00:00.000000000Z",
            "mid": {"o": "1.09100", "h": "1.09500", "l": "1.08900", "c": "1.09300"},
        },
        {
            "complete": True,
            "volume": 11000,
            "time": "2025-01-11T00:00:00.000000000Z",
            "mid": {"o": "1.09300", "h": "1.09700", "l": "1.09100", "c": "1.09600"},
        },
    ],
}

MOCK_ACCOUNT_RESPONSE = {
    "account": {
        "id": "101-001-12345678-001",
        "balance": "10000.00",
        "NAV": "10150.50",
        "openPositionCount": "1",
        "currency": "USD",
    }
}

MOCK_ORDER_FILL_RESPONSE = {
    "orderFillTransaction": {
        "id": "12345",
        "instrument": "EUR_USD",
        "units": "1000",
        "price": "1.09500",
        "time": "2025-01-10T12:00:00.000000000Z",
    }
}

MOCK_POSITIONS_RESPONSE = {
    "positions": [
        {
            "instrument": "EUR_USD",
            "long": {"units": "1000", "averagePrice": "1.09300"},
            "short": {"units": "0"},
            "unrealizedPL": "20.00",
        }
    ]
}


# ── Tests ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_candles(monkeypatch):
    """Candle dataclass fields populated correctly from mock JSON."""
    client = OandaClient(_make_config())

    async def _mock_get(self, url, *, headers=None, params=None, timeout=None):
        return httpx.Response(200, json=MOCK_CANDLES_RESPONSE, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    candles = await client.fetch_candles("EUR_USD", "D", count=2)
    assert len(candles) == 2
    c = candles[0]
    assert isinstance(c, Candle)
    assert c.open == pytest.approx(1.091)
    assert c.high == pytest.approx(1.095)
    assert c.low == pytest.approx(1.089)
    assert c.close == pytest.approx(1.093)
    assert c.volume == 12345
    assert c.complete is True
    assert c.time == "2025-01-10T00:00:00.000000000Z"


@pytest.mark.asyncio
async def test_account_summary(monkeypatch):
    """Balance and equity parsed from mock response."""
    client = OandaClient(_make_config())

    async def _mock_get(self, url, *, headers=None, params=None, timeout=None):
        return httpx.Response(200, json=MOCK_ACCOUNT_RESPONSE, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    summary = await client.get_account_summary()
    assert isinstance(summary, AccountSummary)
    assert summary.balance == pytest.approx(10000.0)
    assert summary.equity == pytest.approx(10150.5)
    assert summary.open_position_count == 1
    assert summary.currency == "USD"


@pytest.mark.asyncio
async def test_order_payload(monkeypatch):
    """Market order JSON matches OANDA v20 spec (direction, units, SL, TP)."""
    client = OandaClient(_make_config())
    captured_body = {}

    async def _mock_post(self, url, *, headers=None, json=None, timeout=None):
        captured_body.update(json)
        return httpx.Response(200, json=MOCK_ORDER_FILL_RESPONSE, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post)

    order_req = OrderRequest(
        instrument="EUR_USD",
        units=1000,
        stop_loss_price=1.08800,
        take_profit_price=1.10000,
    )
    resp = await client.place_order(order_req)

    assert isinstance(resp, OrderResponse)
    assert resp.order_id == "12345"
    assert resp.price == pytest.approx(1.095)

    # Validate the request body structure
    order_body = captured_body["order"]
    assert order_body["type"] == "MARKET"
    assert order_body["instrument"] == "EUR_USD"
    assert order_body["units"] == "1000"
    assert "stopLossOnFill" in order_body
    assert "takeProfitOnFill" in order_body


@pytest.mark.asyncio
async def test_list_positions(monkeypatch):
    """Open positions parsed from mock response."""
    client = OandaClient(_make_config())

    async def _mock_get(self, url, *, headers=None, params=None, timeout=None):
        return httpx.Response(200, json=MOCK_POSITIONS_RESPONSE, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", _mock_get)

    positions = await client.list_open_positions()
    assert len(positions) == 1
    pos = positions[0]
    assert isinstance(pos, Position)
    assert pos.instrument == "EUR_USD"
    assert pos.long_units == pytest.approx(1000.0)
    assert pos.unrealized_pnl == pytest.approx(20.0)
    assert pos.average_price == pytest.approx(1.093)


def test_environment_switching():
    """Practice URL for practice, live URL for live."""
    cfg_practice = _make_config("practice")
    cfg_live = _make_config("live")

    client_practice = OandaClient(cfg_practice)
    client_live = OandaClient(cfg_live)

    assert client_practice._base_url == "https://api-fxpractice.oanda.com"
    assert client_live._base_url == "https://api-fxtrade.oanda.com"
