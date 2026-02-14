"""Strategy data models — typed representations for strategy outputs."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CandleData:
    """A single candlestick bar for strategy consumption."""

    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


@dataclass(frozen=True)
class SRZone:
    """A support or resistance price zone."""

    zone_type: str  # "support" or "resistance"
    price_level: float
    strength: int  # number of touches


@dataclass(frozen=True)
class EntrySignal:
    """A trade entry signal produced by the strategy."""

    direction: str  # "buy" or "sell"
    entry_price: float
    sr_zone: SRZone
    candle_time: str
    reason: str
