"""Internal API routers — /status and /trades endpoints.

No business logic, no DB access. Delegates to repos and shared state.
"""

from typing import Optional

from fastapi import APIRouter, Query


router = APIRouter()

# ── Shared state (set during app startup) ────────────────────────────────

_bot_status: dict = {
    "mode": "idle",
    "running": False,
    "pair": "EUR_USD",
    "equity": None,
    "balance": None,
    "peak_equity": None,
    "drawdown_pct": None,
    "circuit_breaker_active": False,
    "open_positions": 0,
    "last_signal_check": None,
    "uptime_seconds": 0,
}

_trade_repo = None  # Set via configure_routers()


def configure_routers(trade_repo, bot_status: Optional[dict] = None) -> None:
    """Inject dependencies from the application startup.

    Args:
        trade_repo: A ``TradeRepo`` instance (or duck-type for tests).
        bot_status: Optional dict to replace the default status state.
    """
    global _trade_repo, _bot_status  # noqa: PLW0603
    _trade_repo = trade_repo
    if bot_status is not None:
        _bot_status.update(bot_status)


def update_bot_status(**fields) -> None:
    """Update individual fields of the bot status dict."""
    _bot_status.update(fields)


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/status")
async def get_status():
    """Return current bot state — mode, equity, positions, drawdown."""
    return _bot_status


@router.get("/trades")
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
):
    """Return recent trade log entries."""
    if _trade_repo is None:
        return {"trades": [], "total": 0}
    return _trade_repo.get_trades(limit=limit, status_filter=status)
