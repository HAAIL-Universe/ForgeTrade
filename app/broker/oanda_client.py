"""OANDA v20 REST API async client.

Handles all communication with OANDA: candle fetching, account queries,
order placement, and position management.
"""

import asyncio
import logging
from typing import Optional

import httpx

from app.broker.models import (
    AccountSummary,
    Candle,
    ClosedTrade,
    OrderRequest,
    OrderResponse,
    Position,
    Trade,
)
from app.config import Config

logger = logging.getLogger("forgetrade")

# Retry settings
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds; doubles each attempt
_RETRYABLE_STATUS_CODES = {502, 503, 504, 429}


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

    # ── Retry helper ─────────────────────────────────────────────────────

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs,
    ) -> httpx.Response:
        """Execute an HTTP request with exponential-backoff retry.

        Retries on transient server errors (502, 503, 504) and rate-limits
        (429).  Non-retryable errors are raised immediately.
        """
        last_exc: Optional[Exception] = None

        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await getattr(client, method)(
                        url,
                        headers=self._headers,
                        timeout=30.0,
                        **kwargs,
                    )

                if resp.status_code in _RETRYABLE_STATUS_CODES:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "OANDA %s %s returned %d — retry %d/%d in %.1fs",
                        method.upper(), url, resp.status_code,
                        attempt + 1, _MAX_RETRIES, delay,
                    )
                    await asyncio.sleep(delay)
                    last_exc = httpx.HTTPStatusError(
                        f"Server error '{resp.status_code}'",
                        request=resp.request,
                        response=resp,
                    )
                    continue

                resp.raise_for_status()
                return resp

            except httpx.TransportError as exc:
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "OANDA %s %s transport error (%s) — retry %d/%d in %.1fs",
                    method.upper(), url, exc,
                    attempt + 1, _MAX_RETRIES, delay,
                )
                last_exc = exc
                await asyncio.sleep(delay)

        # All retries exhausted — raise the last error
        raise last_exc  # type: ignore[misc]

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

        resp = await self._request_with_retry("get", url, params=params)

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

        resp = await self._request_with_retry("get", url)

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
        # Use appropriate price precision per instrument
        _prec = 2 if "XAU" in order.instrument or "XAG" in order.instrument else 5
        body = {
            "order": {
                "type": "MARKET",
                "instrument": order.instrument,
                "units": str(int(order.units)),
                "stopLossOnFill": {
                    "price": f"{order.stop_loss_price:.{_prec}f}",
                },
                "takeProfitOnFill": {
                    "price": f"{order.take_profit_price:.{_prec}f}",
                },
            }
        }

        resp = await self._request_with_retry("post", url, json=body)

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

        resp = await self._request_with_retry("get", url)

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

    async def list_open_trades(self) -> list[Trade]:
        """Return all open trades with SL/TP details."""
        url = f"{self._base_url}/v3/accounts/{self._account_id}/openTrades"

        resp = await self._request_with_retry("get", url)

        trades: list[Trade] = []
        for t in resp.json().get("trades", []):
            sl_price = None
            tp_price = None
            if "stopLossOrder" in t:
                sl_price = float(t["stopLossOrder"].get("price", 0))
            if "takeProfitOrder" in t:
                tp_price = float(t["takeProfitOrder"].get("price", 0))
            trades.append(
                Trade(
                    trade_id=t["id"],
                    instrument=t["instrument"],
                    units=float(t["currentUnits"]),
                    price=float(t["price"]),
                    unrealized_pnl=float(t.get("unrealizedPL", "0")),
                    stop_loss_price=sl_price,
                    take_profit_price=tp_price,
                    open_time=t.get("openTime", ""),
                )
            )
        return trades

    async def close_position(self, instrument: str) -> dict:
        """Close all units of a position for the given instrument.

        Returns the raw OANDA response dict.
        """
        url = (
            f"{self._base_url}/v3/accounts/{self._account_id}"
            f"/positions/{instrument}/close"
        )
        body = {"longUnits": "ALL", "shortUnits": "ALL"}

        resp = await self._request_with_retry("put", url, json=body)

        return resp.json()

    async def modify_trade_sl(
        self,
        trade_id: str,
        new_sl_price: float,
    ) -> dict:
        """Update the stop-loss on an open trade.

        Args:
            trade_id: OANDA trade ID.
            new_sl_price: New stop-loss price.

        Returns:
            Raw OANDA response dict.
        """
        url = (
            f"{self._base_url}/v3/accounts/{self._account_id}"
            f"/trades/{trade_id}/orders"
        )
        body = {
            "stopLoss": {
                "price": f"{new_sl_price:.5f}",
            }
        }

        resp = await self._request_with_retry("put", url, json=body)

        return resp.json()

    async def list_closed_trades(self, count: int = 50) -> list[ClosedTrade]:
        """Return recently closed trades with P&L and lifecycle data.

        Enriches each trade with SL/TP prices from the opening transaction
        and close reason from the closing transaction, since OANDA strips
        order objects from closed trades.

        Args:
            count: Maximum number of closed trades to return.

        Returns:
            List of ``ClosedTrade`` objects, newest first.
        """
        url = f"{self._base_url}/v3/accounts/{self._account_id}/trades"
        params = {"state": "CLOSED", "count": count}

        resp = await self._request_with_retry("get", url, params=params)

        raw_trades = resp.json().get("trades", [])
        if not raw_trades:
            return []

        # ── Fetch transactions for SL/TP + close reason enrichment ───
        sl_tp_map: dict[str, dict] = {}   # trade_id → {"sl": float|None, "tp": float|None}
        close_reason_map: dict[str, str] = {}  # trade_id → reason string

        try:
            # Compute transaction ID range covering all trades
            trade_ids = [int(t["id"]) for t in raw_trades]
            closing_ids: list[int] = []
            for t in raw_trades:
                closing_ids.extend(
                    int(cid) for cid in t.get("closingTransactionIDs", [])
                )

            min_id = min(trade_ids) - 1  # include the MARKET_ORDER before first trade
            max_id = max(closing_ids) if closing_ids else max(trade_ids) + 5

            # Cap the range to avoid fetching thousands of transactions
            if max_id - min_id > 500:
                min_id = max_id - 500

            txn_url = (
                f"{self._base_url}/v3/accounts/{self._account_id}"
                f"/transactions/idrange"
            )
            txn_resp = await self._request_with_retry(
                "get", txn_url, params={"from": str(min_id), "to": str(max_id)},
            )
            txns = txn_resp.json().get("transactions", [])

            # Index MARKET_ORDER transactions by ID → SL/TP
            market_orders: dict[str, dict] = {}
            for txn in txns:
                if txn.get("type") == "MARKET_ORDER":
                    sl_fill = txn.get("stopLossOnFill")
                    tp_fill = txn.get("takeProfitOnFill")
                    market_orders[txn["id"]] = {
                        "sl": float(sl_fill["price"]) if sl_fill else None,
                        "tp": float(tp_fill["price"]) if tp_fill else None,
                    }

            # Index ORDER_FILL transactions: trade_id → orderID (MARKET_ORDER)
            order_fills: dict[str, str] = {}
            for txn in txns:
                if txn.get("type") == "ORDER_FILL":
                    opened = txn.get("tradeOpened")
                    if opened:
                        order_fills[opened.get("tradeID", "")] = txn.get("orderID", "")

            # Build SL/TP map: trade_id → SL/TP from the originating MARKET_ORDER
            for trade_id, order_id in order_fills.items():
                mo = market_orders.get(order_id)
                if mo:
                    sl_tp_map[trade_id] = mo

            # Build close reason map from closing ORDER_FILL transactions
            for txn in txns:
                if txn.get("type") == "ORDER_FILL" and txn.get("tradesClosed"):
                    reason = txn.get("reason", "")
                    for tc in txn["tradesClosed"]:
                        tid = tc.get("tradeID", "")
                        if tid:
                            close_reason_map[tid] = reason

            # Also check TRADE_CLOSE transactions (some closures use this)
            for txn in txns:
                if txn.get("type") == "ORDER_FILL" and txn.get("tradeReduced"):
                    reduced = txn["tradeReduced"]
                    tid = reduced.get("tradeID", "")
                    if tid and tid not in close_reason_map:
                        close_reason_map[tid] = txn.get("reason", "")

        except Exception:
            logger.debug("Could not enrich closed trades with transaction data")

        # ── Build ClosedTrade objects ────────────────────────────────
        trades: list[ClosedTrade] = []
        for t in raw_trades:
            units = float(t.get("initialUnits", t.get("currentUnits", "0")))
            direction = "long" if units > 0 else "short"
            trade_id = t["id"]

            # SL/TP from transaction enrichment
            enriched = sl_tp_map.get(trade_id, {})
            sl_price = enriched.get("sl")
            tp_price = enriched.get("tp")

            # Close reason from transaction enrichment
            raw_reason = close_reason_map.get(trade_id, "")
            if "TAKE_PROFIT" in raw_reason:
                close_reason = "TAKE_PROFIT"
            elif "STOP_LOSS" in raw_reason and "TRAILING" not in raw_reason:
                close_reason = "STOP_LOSS"
            elif "TRAILING" in raw_reason:
                close_reason = "TRAILING_STOP"
            elif "MARKET_ORDER" in raw_reason or "CLIENT" in raw_reason:
                close_reason = "CLIENT_CLOSE"
            elif "LINKED_TRADE" in raw_reason:
                close_reason = "LINKED_CLOSE"
            elif raw_reason:
                close_reason = raw_reason
            else:
                close_reason = ""

            trades.append(
                ClosedTrade(
                    trade_id=trade_id,
                    instrument=t["instrument"],
                    units=abs(units),
                    entry_price=float(t["price"]),
                    exit_price=float(t.get("averageClosePrice", t["price"])),
                    realized_pnl=float(t.get("realizedPL", "0")),
                    direction=direction,
                    open_time=t.get("openTime", ""),
                    close_time=t.get("closeTime", ""),
                    stop_loss_price=sl_price,
                    take_profit_price=tp_price,
                    close_reason=close_reason,
                )
            )
        return trades