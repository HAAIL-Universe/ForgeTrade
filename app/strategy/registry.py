"""Strategy registry — maps strategy names to classes.

Used by EngineManager to instantiate strategy from StreamConfig.strategy.
"""

from app.strategy.base import StrategyProtocol
from app.strategy.sr_rejection import SRRejectionStrategy
from app.strategy.trend_scalp import TrendScalpStrategy


STRATEGY_REGISTRY: dict[str, type] = {
    "sr_rejection": SRRejectionStrategy,
    "trend_scalp": TrendScalpStrategy,
}


def get_strategy(name: str) -> StrategyProtocol:
    """Look up and instantiate a strategy by registry key.

    Raises ``KeyError`` if the strategy name is not registered.
    """
    if name not in STRATEGY_REGISTRY:
        raise KeyError(
            f"Unknown strategy '{name}'. "
            f"Available: {', '.join(STRATEGY_REGISTRY.keys())}"
        )
    return STRATEGY_REGISTRY[name]()
