"""Drawdown tracking and circuit breaker — pure math, no I/O.

Tracks peak equity and current drawdown percentage.  The circuit breaker
activates when drawdown exceeds the configured threshold (default 10 %).
"""


class DrawdownTracker:
    """Tracks equity peaks and computes drawdown metrics.

    Args:
        initial_equity: Starting account equity.
        max_drawdown_pct: Drawdown threshold that triggers the circuit breaker
                          (percentage, e.g. 10.0 for 10 %).
    """

    def __init__(
        self,
        initial_equity: float,
        max_drawdown_pct: float = 10.0,
    ) -> None:
        if initial_equity <= 0:
            raise ValueError(
                f"initial_equity must be positive, got {initial_equity}"
            )
        self._peak_equity: float = initial_equity
        self._current_equity: float = initial_equity
        self._max_drawdown_pct: float = max_drawdown_pct

    # ── Mutation ─────────────────────────────────────────────────────────

    def update(self, equity: float) -> None:
        """Update with the latest equity value.

        If *equity* exceeds the current peak, the peak is raised.
        """
        self._current_equity = equity
        if equity > self._peak_equity:
            self._peak_equity = equity

    # ── Queries ──────────────────────────────────────────────────────────

    @property
    def peak_equity(self) -> float:
        """Highest equity recorded."""
        return self._peak_equity

    @property
    def current_equity(self) -> float:
        """Most recently recorded equity."""
        return self._current_equity

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown as a percentage of peak equity."""
        if self._peak_equity == 0:
            return 0.0
        return (
            (self._peak_equity - self._current_equity) / self._peak_equity
        ) * 100.0

    @property
    def circuit_breaker_active(self) -> bool:
        """``True`` when drawdown has reached or exceeded the threshold."""
        return self.drawdown_pct >= self._max_drawdown_pct
