"""Stream configuration dataclass.

Represents one trading stream in the multi-stream engine.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StreamConfig:
    """Configuration for a single trading stream.

    Each stream runs its own ``TradingEngine`` with its own instrument,
    strategy, timeframes, and polling interval.
    """

    name: str
    instrument: str
    strategy: str  # strategy registry key, e.g. "sr_rejection"
    timeframes: list[str] = field(default_factory=lambda: ["D", "H4"])
    poll_interval_seconds: int = 300
    risk_per_trade_pct: float = 1.0
    max_concurrent_positions: int = 1
    session_start_utc: int = 7
    session_end_utc: int = 21
    enabled: bool = True
    rr_ratio: float | None = None  # Per-stream R:R override; None = strategy default
    rl_filter: dict | None = None  # ForgeAgent RL filter config (mode, model_path, threshold)
