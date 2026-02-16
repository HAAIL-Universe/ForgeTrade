"""Internal API routers — /status, /trades, /positions, /signals endpoints.

No business logic, no DB access. Delegates to repos, broker, and shared state.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query


router = APIRouter()

# ── Shared state (set during app startup) ────────────────────────────────

_DEFAULT_STREAM_STATUS: dict = {
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
    "cycle_count": 0,
    "last_cycle_at": None,
    "last_signal_time": None,
    "last_order_time": None,
}

# Keyed by stream name → status dict
_stream_statuses: dict[str, dict] = {
    "default": {**_DEFAULT_STREAM_STATUS, "stream_name": "default"},
}

_trade_repo = None   # Set via configure_routers()
_broker = None       # Set via configure_routers()
_pending_signal = None  # Updated by engine after evaluate_signal()


def configure_routers(
    trade_repo,
    bot_status: Optional[dict] = None,
    broker=None,
) -> None:
    """Inject dependencies from the application startup.

    Args:
        trade_repo: A ``TradeRepo`` instance (or duck-type for tests).
        bot_status: Optional dict to replace the default status state.
        broker: An ``OandaClient`` instance for position queries.
    """
    global _trade_repo, _broker  # noqa: PLW0603
    _trade_repo = trade_repo
    _broker = broker
    if bot_status is not None:
        stream_name = bot_status.get("stream_name", "default")
        _stream_statuses.setdefault(stream_name, {**_DEFAULT_STREAM_STATUS})
        _stream_statuses[stream_name].update(bot_status)


def update_bot_status(stream_name: str = "default", **fields) -> None:
    """Update individual fields of a stream's status dict."""
    if stream_name not in _stream_statuses:
        _stream_statuses[stream_name] = {
            **_DEFAULT_STREAM_STATUS,
            "stream_name": stream_name,
        }
    _stream_statuses[stream_name].update(fields)


def update_pending_signal(signal_data: Optional[dict]) -> None:
    """Store the last evaluated signal for the watchlist endpoint."""
    global _pending_signal  # noqa: PLW0603
    _pending_signal = signal_data


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/status")
async def get_status():
    """Return status for all streams."""
    return {"streams": _stream_statuses}


@router.get("/status/{stream_name}")
async def get_stream_status(stream_name: str):
    """Return status for a single stream."""
    status = _stream_statuses.get(stream_name)
    if status is None:
        return {"error": f"Unknown stream: {stream_name}"}
    return status


@router.get("/trades")
async def get_trades(
    limit: int = Query(default=20, ge=1, le=100),
    status: Optional[str] = Query(default=None),
    stream: Optional[str] = Query(default=None),
):
    """Return recent trade log entries."""
    if _trade_repo is None:
        return {"trades": [], "total": 0}
    return _trade_repo.get_trades(
        limit=limit, status_filter=status, stream_name=stream,
    )


@router.get("/positions")
async def get_positions():
    """Return current open positions from OANDA."""
    if _broker is None:
        return {"positions": []}
    try:
        positions = await _broker.list_open_positions()
        result = []
        for p in positions:
            direction = "long" if p.long_units > 0 else "short"
            units = p.long_units if p.long_units > 0 else abs(p.short_units)
            result.append({
                "instrument": p.instrument,
                "direction": direction,
                "units": units,
                "avg_price": p.average_price,
                "unrealized_pnl": p.unrealized_pnl,
            })
        return {"positions": result}
    except Exception:
        return {"positions": []}


@router.get("/signals/pending")
async def get_pending_signals():
    """Return the last evaluated signal (watchlist)."""
    return {"signal": _pending_signal}


@router.get("/trades/closed")
async def get_closed_trades(
    limit: int = Query(default=20, ge=1, le=100),
    stream: Optional[str] = Query(default=None),
):
    """Return closed trades with P&L summary."""
    if _trade_repo is None:
        return {"trades": [], "total": 0, "total_pnl": 0.0}
    result = _trade_repo.get_trades(
        limit=limit, status_filter="closed", stream_name=stream,
    )
    total_pnl = sum(t.get("pnl", 0) or 0 for t in result.get("trades", []))
    result["total_pnl"] = round(total_pnl, 2)
    return result
