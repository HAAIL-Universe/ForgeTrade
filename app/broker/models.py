"""Broker data models — typed representations of OANDA v20 API objects."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Candle:
    """A single candlestick bar."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    complete: bool


@dataclass(frozen=True)
class AccountSummary:
    """Summary of an OANDA account."""

    account_id: str
    balance: float
    equity: float
    open_position_count: int
    currency: str


@dataclass(frozen=True)
class OrderRequest:
    """A market order request payload."""

    instrument: str
    units: float  # positive=buy, negative=sell
    stop_loss_price: float
    take_profit_price: float


@dataclass(frozen=True)
class OrderResponse:
    """Response from placing an order."""

    order_id: str
    instrument: str
    units: float
    price: float
    time: str


@dataclass(frozen=True)
class Position:
    """An open position."""

    instrument: str
    long_units: float
    short_units: float
    unrealized_pnl: float
    average_price: float
