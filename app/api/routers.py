"""Internal API routers — /status, /trades, /positions, /signals, /settings endpoints.

No business logic, no DB access. Delegates to repos, broker, and shared state.
"""

import json
import logging
import pathlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Query

from app.models.stream_config import StreamConfig

logger = logging.getLogger("forgetrade")
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
_strategy_insight: dict = {}  # Updated by engine each cycle
_engine_manager = None  # Set via configure_routers()
_forge_json_path: Optional[pathlib.Path] = None  # Set via configure_routers()

# Live settings — mutable at runtime, persisted to forge.json
_live_settings: dict = {
    "risk_per_trade_pct": 1.0,
    "rr_ratio": 2.0,
    "max_drawdown_pct": 10.0,
    "session_start_utc": 7,
    "session_end_utc": 21,
    "max_concurrent_positions": 1,
    "poll_interval_seconds": 300,
}


def configure_routers(
    trade_repo,
    bot_status: Optional[dict] = None,
    broker=None,
    engine_manager=None,
    forge_json_path: Optional[pathlib.Path] = None,
) -> None:
    """Inject dependencies from the application startup.

    Args:
        trade_repo: A ``TradeRepo`` instance (or duck-type for tests).
        bot_status: Optional dict to replace the default status state.
        broker: An ``OandaClient`` instance for position queries.
        engine_manager: An ``EngineManager`` instance for control actions.
        forge_json_path: Path to ``forge.json`` for settings persistence.
    """
    global _trade_repo, _broker, _engine_manager, _forge_json_path  # noqa: PLW0603
    _trade_repo = trade_repo
    _broker = broker
    _engine_manager = engine_manager
    _forge_json_path = forge_json_path
    if bot_status is not None:
        stream_name = bot_status.get("stream_name", "default")
        _stream_statuses.setdefault(stream_name, {**_DEFAULT_STREAM_STATUS})
        _stream_statuses[stream_name].update(bot_status)
    # Seed live settings from forge.json streams
    if forge_json_path and forge_json_path.exists():
        try:
            data = json.loads(forge_json_path.read_text(encoding="utf-8"))
            streams = data.get("streams", [])
            if streams:
                s = streams[0]
                _live_settings["risk_per_trade_pct"] = s.get("risk_per_trade_pct", 1.0)
                _live_settings["max_concurrent_positions"] = s.get("max_concurrent_positions", 1)
                _live_settings["session_start_utc"] = s.get("session_start_utc", 7)
                _live_settings["session_end_utc"] = s.get("session_end_utc", 21)
                _live_settings["poll_interval_seconds"] = s.get("poll_interval_seconds", 300)
                _live_settings["max_drawdown_pct"] = data.get("max_drawdown_pct", 10.0)
        except Exception:
            pass


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


def update_strategy_insight(stream_name: str, insight: dict) -> None:
    """Store per-cycle strategy analysis for the dashboard."""
    _strategy_insight[stream_name] = insight


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


@router.get("/strategy/insight")
async def get_strategy_insight():
    """Return live strategy analysis with entry checklist."""
    return {"insights": _strategy_insight}


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


# ── Settings ─────────────────────────────────────────────────────────────


def get_live_settings() -> dict:
    """Return the current live settings dict (for engine reads)."""
    return dict(_live_settings)


@router.get("/settings")
async def get_settings():
    """Return current runtime settings."""
    return dict(_live_settings)


@router.post("/settings")
async def post_settings(body: dict):
    """Update runtime settings and persist to forge.json.

    Validates ranges before applying. Returns updated settings.
    """
    errors = []

    if "risk_per_trade_pct" in body:
        v = float(body["risk_per_trade_pct"])
        if not 0.1 <= v <= 5.0:
            errors.append("risk_per_trade_pct must be 0.1–5.0")
        else:
            _live_settings["risk_per_trade_pct"] = round(v, 2)

    if "rr_ratio" in body:
        v = float(body["rr_ratio"])
        if not 1.0 <= v <= 5.0:
            errors.append("rr_ratio must be 1.0–5.0")
        else:
            _live_settings["rr_ratio"] = round(v, 1)

    if "max_drawdown_pct" in body:
        v = float(body["max_drawdown_pct"])
        if not 1.0 <= v <= 25.0:
            errors.append("max_drawdown_pct must be 1.0–25.0")
        else:
            _live_settings["max_drawdown_pct"] = round(v, 1)

    if "session_start_utc" in body:
        v = int(body["session_start_utc"])
        if not 0 <= v <= 23:
            errors.append("session_start_utc must be 0–23")
        else:
            _live_settings["session_start_utc"] = v

    if "session_end_utc" in body:
        v = int(body["session_end_utc"])
        if not 0 <= v <= 23:
            errors.append("session_end_utc must be 0–23")
        else:
            _live_settings["session_end_utc"] = v

    if "max_concurrent_positions" in body:
        v = int(body["max_concurrent_positions"])
        if not 1 <= v <= 10:
            errors.append("max_concurrent_positions must be 1–10")
        else:
            _live_settings["max_concurrent_positions"] = v

    if "poll_interval_seconds" in body:
        v = int(body["poll_interval_seconds"])
        if not 10 <= v <= 3600:
            errors.append("poll_interval_seconds must be 10–3600")
        else:
            _live_settings["poll_interval_seconds"] = v

    if errors:
        return {"status": "error", "errors": errors}

    # Persist to forge.json
    _persist_settings()

    # Apply to running engines
    _apply_settings_to_engines()

    logger.info("Settings updated: %s", _live_settings)
    return {"status": "ok", **_live_settings}


def _persist_settings() -> None:
    """Write current live settings back to forge.json streams."""
    if not _forge_json_path or not _forge_json_path.exists():
        return
    try:
        data = json.loads(_forge_json_path.read_text(encoding="utf-8"))
        for s in data.get("streams", []):
            s["risk_per_trade_pct"] = _live_settings["risk_per_trade_pct"]
            s["max_concurrent_positions"] = _live_settings["max_concurrent_positions"]
            s["session_start_utc"] = _live_settings["session_start_utc"]
            s["session_end_utc"] = _live_settings["session_end_utc"]
            s["poll_interval_seconds"] = _live_settings["poll_interval_seconds"]
        data["max_drawdown_pct"] = _live_settings["max_drawdown_pct"]
        data["rr_ratio"] = _live_settings["rr_ratio"]
        _forge_json_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Failed to persist settings: %s", exc)


def _apply_settings_to_engines() -> None:
    """Push live settings into running engine instances."""
    if not _engine_manager:
        return
    for name, engine in _engine_manager.engines.items():
        sc = engine._stream_config
        if sc:
            # StreamConfig is frozen, so we replace it
            new_sc = StreamConfig(
                name=sc.name,
                instrument=sc.instrument,
                strategy=sc.strategy,
                timeframes=sc.timeframes,
                poll_interval_seconds=_live_settings["poll_interval_seconds"],
                risk_per_trade_pct=_live_settings["risk_per_trade_pct"],
                max_concurrent_positions=_live_settings["max_concurrent_positions"],
                session_start_utc=_live_settings["session_start_utc"],
                session_end_utc=_live_settings["session_end_utc"],
                enabled=sc.enabled,
            )
            engine._stream_config = new_sc
        # Update drawdown threshold
        if engine._drawdown:
            engine._drawdown._max_drawdown_pct = _live_settings["max_drawdown_pct"]


# ── Control actions ──────────────────────────────────────────────────────


@router.post("/control/pause")
async def pause_all():
    """Pause all streams (stop engines but keep API alive)."""
    if _engine_manager:
        _engine_manager.stop_all()
        for name in _engine_manager.stream_names:
            update_bot_status(stream_name=name, running=False, mode="paused")
    logger.info("All streams paused via dashboard.")
    return {"status": "paused"}


@router.post("/control/resume")
async def resume_all():
    """Resume all streams."""
    if _engine_manager:
        import asyncio
        for name, engine in _engine_manager.engines.items():
            if not engine._running:
                engine._running = True
                asyncio.create_task(engine.run())
                update_bot_status(stream_name=name, running=True, mode="paper")
    logger.info("All streams resumed via dashboard.")
    return {"status": "resumed"}


@router.post("/control/emergency-stop")
async def emergency_stop():
    """Emergency stop — immediately halt all streams."""
    if _engine_manager:
        _engine_manager.stop_all()
        for name in _engine_manager.stream_names:
            update_bot_status(
                stream_name=name, running=False, mode="stopped",
                circuit_breaker_active=True,
            )
    logger.warning("EMERGENCY STOP triggered via dashboard.")
    return {"status": "emergency_stopped"}
