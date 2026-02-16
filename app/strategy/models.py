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


# ── Instrument metadata ──────────────────────────────────────────────────

INSTRUMENT_PIP_VALUES: dict[str, float] = {
    "EUR_USD": 0.0001,
    "GBP_USD": 0.0001,
    "USD_JPY": 0.01,
    "USD_CHF": 0.0001,
    "AUD_USD": 0.0001,
    "NZD_USD": 0.0001,
    "USD_CAD": 0.0001,
    "XAU_USD": 0.01,
    "XAG_USD": 0.001,
}
