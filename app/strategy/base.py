"""Strategy protocol and shared result type.

Defines the interface that all strategies must implement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from app.strategy.models import EntrySignal


@dataclass(frozen=True)
class StrategyResult:
    """Bundles a signal with its risk parameters.

    Returned by strategies so the engine doesn't need to know
    which indicator or zone method was used.
    """

    signal: EntrySignal
    sl: float
    tp: float
    atr: Optional[float] = None


@runtime_checkable
class StrategyProtocol(Protocol):
    """Interface that all trading strategies must satisfy."""

    async def evaluate(self, broker, config) -> Optional[StrategyResult]:
        """Evaluate market conditions and return a trade setup or None."""
        ...
