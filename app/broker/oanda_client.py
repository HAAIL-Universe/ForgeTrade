"""OANDA v20 REST API async client.

Handles all communication with OANDA: candle fetching, account queries,
order placement, and position management.
"""

from typing import Optional

import httpx

from app.broker.models import (
    AccountSummary,
    Candle,
    OrderRequest,
    OrderResponse,
    Position,
)
from app.config import Config


class OandaClient:
    """Async client wrapping OANDA v20 REST API."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._base_url = config.oanda_base_url
        self._account_id = config.oanda_account_id
        self._headers = {
            "Authorization": f"Bearer {config.oanda_api_token}",
            "Content-Type": "application/json",
        }

    # ── Candle data ──────────────────────────────────────────────────────

    async def fetch_candles(
        self,
        instrument: str,
        granularity: str,
        count: int = 50,
    ) -> list[Candle]:
        """Fetch candlestick data from OANDA.

        Args:
            instrument: e.g. ``"EUR_USD"``
            granularity: e.g. ``"D"`` (daily), ``"H4"`` (4-hour)
            count: number of candles to request (max 5000)

        Returns:
            List of ``Candle`` objects ordered oldest-first.
        """
        url = (
            f"{self._base_url}/v3/instruments/{instrument}/candles"
        )
        params = {
            "granularity": granularity,
            "count": count,
            "price": "M",  # mid prices
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers, params=params, timeout=30.0
            )
            resp.raise_for_status()

        data = resp.json()
        candles: list[Candle] = []
        for c in data.get("candles", []):
            mid = c["mid"]
            candles.append(
                Candle(
                    time=c["time"],
                    open=float(mid["o"]),
                    high=float(mid["h"]),
                    low=float(mid["l"]),
                    close=float(mid["c"]),
                    volume=int(c["volume"]),
                    complete=bool(c["complete"]),
                )
            )
        return candles

    # ── Account ──────────────────────────────────────────────────────────

    async def get_account_summary(self) -> AccountSummary:
        """Query OANDA for account balance, equity, and open position count."""
        url = f"{self._base_url}/v3/accounts/{self._account_id}/summary"

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers, timeout=30.0
            )
            resp.raise_for_status()

        acct = resp.json()["account"]
        return AccountSummary(
            account_id=acct["id"],
            balance=float(acct["balance"]),
            equity=float(acct["NAV"]),
            open_position_count=int(acct["openPositionCount"]),
            currency=acct["currency"],
        )

    # ── Orders ───────────────────────────────────────────────────────────

    async def place_order(self, order: OrderRequest) -> OrderResponse:
        """Place a market order with stop-loss and take-profit.

        Args:
            order: ``OrderRequest`` with instrument, units, SL, and TP.

        Returns:
            ``OrderResponse`` with the fill details.
        """
        url = f"{self._base_url}/v3/accounts/{self._account_id}/orders"
        body = {
            "order": {
                "type": "MARKET",
                "instrument": order.instrument,
                "units": str(order.units),
                "stopLossOnFill": {
                    "price": f"{order.stop_loss_price:.5f}",
                },
                "takeProfitOnFill": {
                    "price": f"{order.take_profit_price:.5f}",
                },
            }
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers, json=body, timeout=30.0
            )
            resp.raise_for_status()

        data = resp.json()
        fill = data["orderFillTransaction"]
        return OrderResponse(
            order_id=fill["id"],
            instrument=fill["instrument"],
            units=float(fill["units"]),
            price=float(fill["price"]),
            time=fill["time"],
        )

    # ── Positions ────────────────────────────────────────────────────────

    async def list_open_positions(self) -> list[Position]:
        """Return all open positions on the account."""
        url = f"{self._base_url}/v3/accounts/{self._account_id}/openPositions"

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers, timeout=30.0
            )
            resp.raise_for_status()

        positions: list[Position] = []
        for p in resp.json().get("positions", []):
            long_units = float(p.get("long", {}).get("units", "0"))
            short_units = float(p.get("short", {}).get("units", "0"))
            unrealized = float(p.get("unrealizedPL", "0"))
            avg_price = 0.0
            if long_units != 0:
                avg_price = float(p["long"].get("averagePrice", "0"))
            elif short_units != 0:
                avg_price = float(p["short"].get("averagePrice", "0"))
            positions.append(
                Position(
                    instrument=p["instrument"],
                    long_units=long_units,
                    short_units=short_units,
                    unrealized_pnl=unrealized,
                    average_price=avg_price,
                )
            )
        return positions

    async def close_position(self, instrument: str) -> dict:
        """Close all units of a position for the given instrument.

        Returns the raw OANDA response dict.
        """
        url = (
            f"{self._base_url}/v3/accounts/{self._account_id}"
            f"/positions/{instrument}/close"
        )
        body = {"longUnits": "ALL", "shortUnits": "ALL"}

        async with httpx.AsyncClient() as client:
            resp = await client.put(
                url, headers=self._headers, json=body, timeout=30.0
            )
            resp.raise_for_status()

        return resp.json()
