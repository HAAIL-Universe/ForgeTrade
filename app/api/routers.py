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
    "strategy": None,
    "equity": None,
    "balance": None,
    "peak_equity": None,
    "drawdown_pct": None,
    "circuit_breaker_active": False,
    "open_positions": 0,
    "last_signal_check": None,
    "uptime_seconds": 0,
    "started_at": None,
    "cycle_count": 0,
    "last_cycle_at": None,
    "last_signal_time": None,
    "last_order_time": None,
}

# Keyed by stream name → status dict
_stream_statuses: dict[str, dict] = {}

_trade_repo = None   # Set via configure_routers()
_broker = None       # Set via configure_routers()
_pending_signal = None  # Updated by engine after evaluate_signal()
_strategy_insight: dict = {}  # Updated by engine each cycle
_signal_history: list = []  # Recent signal log (max 50 entries)
_rl_decisions: list = []  # Ring buffer of ForgeAgent decisions (max 20)
_engine_manager = None  # Set via configure_routers()
_forge_json_path: Optional[pathlib.Path] = None  # Set via configure_routers()

# Live settings — mutable at runtime, persisted to forge.json
_live_settings: dict = {
    "max_drawdown_pct": 10.0,
    "session_start_utc": 7,
    "session_end_utc": 21,
    "max_concurrent_positions": 1,
    "poll_interval_seconds": 300,
    "leverage": 30,
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
                _live_settings["max_concurrent_positions"] = s.get("max_concurrent_positions", 1)
                _live_settings["session_start_utc"] = s.get("session_start_utc", 7)
                _live_settings["session_end_utc"] = s.get("session_end_utc", 21)
                _live_settings["poll_interval_seconds"] = s.get("poll_interval_seconds", 300)
                _live_settings["max_drawdown_pct"] = data.get("max_drawdown_pct", 10.0)
                _live_settings["leverage"] = data.get("leverage", 30)
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
    """Store the last evaluated signal for the watchlist endpoint.

    Appends every evaluation to the signal history log — buy/sell
    signals, skips, and engine-level blocks — so the dashboard shows
    a complete decision timeline.
    """
    global _pending_signal  # noqa: PLW0603
    _pending_signal = signal_data
    if signal_data:
        entry = {
            "pair": signal_data.get("pair", ""),
            "direction": signal_data.get("direction") or "—",
            "status": signal_data.get("status", ""),
            "reason": signal_data.get("reason", ""),
            "zone_price": signal_data.get("zone_price"),
            "evaluated_at": signal_data.get("evaluated_at", ""),
            "stream_name": signal_data.get("stream_name", ""),
        }
        _signal_history.append(entry)
        # Cap at 50 entries
        if len(_signal_history) > 50:
            del _signal_history[0]


def update_strategy_insight(stream_name: str, insight: dict) -> None:
    """Store per-cycle strategy analysis for the dashboard."""
    _strategy_insight[stream_name] = insight


def push_rl_decision(decision: dict) -> None:
    """Append an RL agent decision to the ring buffer (max 20)."""
    _rl_decisions.append(decision)
    if len(_rl_decisions) > 20:
        del _rl_decisions[0]


# ── Endpoints ────────────────────────────────────────────────────────────


@router.get("/status")
async def get_status():
    """Return status for all streams (excludes legacy 'default' entry)."""
    filtered = {k: v for k, v in _stream_statuses.items() if k != "default"}
    return {"streams": filtered}


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
    """Return current open positions from OANDA with SL/TP details."""
    if _broker is None:
        return {"positions": []}
    try:
        trades = await _broker.list_open_trades()
        result = []
        for t in trades:
            direction = "long" if t.units > 0 else "short"
            result.append({
                "instrument": t.instrument,
                "direction": direction,
                "units": abs(t.units),
                "avg_price": t.price,
                "unrealized_pnl": t.unrealized_pnl,
                "stop_loss": t.stop_loss_price,
                "take_profit": t.take_profit_price,
                "open_time": t.open_time,
            })
        return {"positions": result}
    except Exception:
        # Fallback to position-level data (no SL/TP)
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
                    "stop_loss": None,
                    "take_profit": None,
                    "open_time": None,
                })
            return {"positions": result}
        except Exception:
            return {"positions": []}


@router.get("/signals/pending")
async def get_pending_signals():
    """Return the last evaluated signal (watchlist)."""
    return {"signal": _pending_signal}


@router.get("/signals/history")
async def get_signal_history(
    limit: int = Query(default=20, ge=1, le=50),
):
    """Return recent signal log (buy/sell signals that were evaluated)."""
    recent = _signal_history[-limit:]
    recent.reverse()  # newest first
    return {"signals": recent}


@router.get("/strategy/insight")
async def get_strategy_insight():
    """Return live strategy analysis with entry checklist."""
    return {"insights": _strategy_insight, "rl_decisions": list(_rl_decisions)}


@router.get("/account")
async def get_account():
    """Return live account summary directly from OANDA.

    Provides fresh equity, balance, and unrealized P&L on every poll
    rather than relying on cached engine-cycle data.
    """
    if _broker is None:
        return {"account": None}
    try:
        summary = await _broker.get_account_summary()
        # Aggregate drawdown: take the worst (max) drawdown_pct across all streams
        dd_values = [
            s.get("drawdown_pct")
            for s in _stream_statuses.values()
            if s.get("drawdown_pct") is not None
        ]
        account_drawdown = round(max(dd_values), 2) if dd_values else 0.0
        return {
            "account": {
                "equity": summary.equity,
                "balance": summary.balance,
                "unrealized_pnl": round(summary.equity - summary.balance, 2),
                "open_position_count": summary.open_position_count,
                "currency": summary.currency,
                "drawdown_pct": account_drawdown,
            }
        }
    except Exception:
        return {"account": None}


@router.get("/trades/closed")
async def get_closed_trades(
    limit: int = Query(default=50, ge=1, le=100),
    stream: Optional[str] = Query(default=None),
):
    """Return closed trades with P&L summary.

    Queries OANDA directly for closed trade history. Falls back to
    the local trade_repo if the broker is unavailable.
    """
    # Try OANDA first — this has real close prices, P&L, timestamps
    if _broker is not None:
        try:
            closed = await _broker.list_closed_trades(count=limit)
            trades = []
            for ct in closed:
                trades.append({
                    "pair": ct.instrument,
                    "direction": ct.direction,
                    "units": ct.units,
                    "entry_price": ct.entry_price,
                    "exit_price": ct.exit_price,
                    "pnl": ct.realized_pnl,
                    "stop_loss": ct.stop_loss_price,
                    "take_profit": ct.take_profit_price,
                    "opened_at": ct.open_time,
                    "closed_at": ct.close_time,
                    "close_reason": ct.close_reason,
                    "status": "closed",
                })
            total_pnl = sum(t["pnl"] for t in trades)
            return {
                "trades": trades,
                "total": len(trades),
                "total_pnl": round(total_pnl, 2),
            }
        except Exception:
            pass  # Fall through to trade_repo

    # Fallback: local DB
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

    if "max_drawdown_pct" in body:
        v = float(body["max_drawdown_pct"])
        if not 1.0 <= v <= 25.0:
            errors.append("max_drawdown_pct must be 1.0–25.0")
        else:
            _live_settings["max_drawdown_pct"] = round(v, 1)


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
    if "leverage" in body:
        v = int(body["leverage"])
        if not 1 <= v <= 500:
            errors.append("leverage must be 1\u2013500")
        else:
            _live_settings["leverage"] = v
    if errors:
        return {"status": "error", "errors": errors}

    # Persist to forge.json
    _persist_settings()

    # Apply to running engines
    _apply_settings_to_engines()

    logger.info("Settings updated: %s", _live_settings)
    return {"status": "ok", **_live_settings}


def _persist_settings() -> None:
    """Write current live settings back to forge.json (global fields only)."""
    if not _forge_json_path or not _forge_json_path.exists():
        return
    try:
        data = json.loads(_forge_json_path.read_text(encoding="utf-8"))
        for s in data.get("streams", []):
            s["max_concurrent_positions"] = _live_settings["max_concurrent_positions"]
            s["poll_interval_seconds"] = _live_settings["poll_interval_seconds"]
        data["max_drawdown_pct"] = _live_settings["max_drawdown_pct"]
        data["leverage"] = _live_settings["leverage"]
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
            # Preserve per-stream risk_per_trade_pct and rr_ratio
            new_sc = StreamConfig(
                name=sc.name,
                instrument=sc.instrument,
                strategy=sc.strategy,
                timeframes=sc.timeframes,
                poll_interval_seconds=_live_settings["poll_interval_seconds"],
                risk_per_trade_pct=sc.risk_per_trade_pct,
                max_concurrent_positions=_live_settings["max_concurrent_positions"],
                session_start_utc=sc.session_start_utc,
                session_end_utc=sc.session_end_utc,
                enabled=sc.enabled,
                rr_ratio=sc.rr_ratio,
            )
            engine._stream_config = new_sc
        # Update drawdown threshold
        if engine._drawdown:
            engine._drawdown._max_drawdown_pct = _live_settings["max_drawdown_pct"]


# ── Per-stream settings ─────────────────────────────────────────────────────


@router.get("/stream-settings")
async def get_stream_settings():
    """Return per-stream risk and R:R settings."""
    entries = []
    if _engine_manager:
        for name, engine in _engine_manager.engines.items():
            sc = engine._stream_config
            if sc:
                entries.append({
                    "name": sc.name,
                    "instrument": sc.instrument,
                    "strategy": sc.strategy,
                    "risk_per_trade_pct": sc.risk_per_trade_pct,
                    "rr_ratio": sc.rr_ratio,
                    "session_start_utc": sc.session_start_utc,
                    "session_end_utc": sc.session_end_utc,
                })
    elif _forge_json_path and _forge_json_path.exists():
        try:
            data = json.loads(_forge_json_path.read_text(encoding="utf-8"))
            for s in data.get("streams", []):
                entries.append({
                    "name": s["name"],
                    "instrument": s["instrument"],
                    "strategy": s["strategy"],
                    "risk_per_trade_pct": s.get("risk_per_trade_pct", 1.0),
                    "rr_ratio": s.get("rr_ratio"),
                    "session_start_utc": s.get("session_start_utc", 0),
                    "session_end_utc": s.get("session_end_utc", 24),
                })
        except Exception:
            pass
    return {"streams": entries}


@router.post("/stream-settings")
async def post_stream_settings(body: dict):
    """Update per-stream risk and R:R settings.

    Expects ``{"streams": [{"name": "...", "risk_per_trade_pct": ..., "rr_ratio": ...}]}``.
    """
    updates = body.get("streams", [])
    if not updates:
        return {"status": "error", "errors": ["No stream updates provided"]}

    errors = []
    for upd in updates:
        name = upd.get("name")
        if not name:
            errors.append("Missing stream name")
            continue
        if "risk_per_trade_pct" in upd:
            v = float(upd["risk_per_trade_pct"])
            if not 0.1 <= v <= 5.0:
                errors.append(f"{name}: risk_per_trade_pct must be 0.1–5.0")
                continue
        if "rr_ratio" in upd and upd["rr_ratio"] is not None:
            v = float(upd["rr_ratio"])
            if not 0.5 <= v <= 10.0:
                errors.append(f"{name}: rr_ratio must be 0.5–10.0")
                continue
        if "session_start_utc" in upd:
            v = int(upd["session_start_utc"])
            if not 0 <= v <= 23:
                errors.append(f"{name}: session_start_utc must be 0\u201323")
                continue
        if "session_end_utc" in upd:
            v = int(upd["session_end_utc"])
            if not 1 <= v <= 24:
                errors.append(f"{name}: session_end_utc must be 1\u201324")
                continue
    if errors:
        return {"status": "error", "errors": errors}

    # Apply to running engines
    if _engine_manager:
        for upd in updates:
            name = upd["name"]
            engine = _engine_manager.engines.get(name)
            if not engine or not engine._stream_config:
                continue
            sc = engine._stream_config
            new_risk = float(upd.get("risk_per_trade_pct", sc.risk_per_trade_pct))
            new_rr = upd.get("rr_ratio", sc.rr_ratio)
            if new_rr is not None:
                new_rr = float(new_rr)
            new_sess_start = int(upd.get("session_start_utc", sc.session_start_utc))
            new_sess_end = int(upd.get("session_end_utc", sc.session_end_utc))
            new_sc = StreamConfig(
                name=sc.name,
                instrument=sc.instrument,
                strategy=sc.strategy,
                timeframes=sc.timeframes,
                poll_interval_seconds=sc.poll_interval_seconds,
                risk_per_trade_pct=round(new_risk, 2),
                max_concurrent_positions=sc.max_concurrent_positions,
                session_start_utc=new_sess_start,
                session_end_utc=new_sess_end,
                enabled=sc.enabled,
                rr_ratio=round(new_rr, 1) if new_rr is not None else None,
            )
            engine._stream_config = new_sc

    # Persist to forge.json
    _persist_stream_settings(updates)

    logger.info("Stream settings updated for: %s", [u["name"] for u in updates])
    return {"status": "ok"}


def _persist_stream_settings(updates: list[dict]) -> None:
    """Write per-stream risk and R:R back to forge.json."""
    if not _forge_json_path or not _forge_json_path.exists():
        return
    try:
        data = json.loads(_forge_json_path.read_text(encoding="utf-8"))
        update_map = {u["name"]: u for u in updates}
        for s in data.get("streams", []):
            if s["name"] in update_map:
                upd = update_map[s["name"]]
                if "risk_per_trade_pct" in upd:
                    s["risk_per_trade_pct"] = round(float(upd["risk_per_trade_pct"]), 2)
                if "rr_ratio" in upd:
                    rr = upd["rr_ratio"]
                    s["rr_ratio"] = round(float(rr), 1) if rr is not None else None
                if "session_start_utc" in upd:
                    s["session_start_utc"] = int(upd["session_start_utc"])
                if "session_end_utc" in upd:
                    s["session_end_utc"] = int(upd["session_end_utc"])
        _forge_json_path.write_text(
            json.dumps(data, indent=2) + "\n", encoding="utf-8",
        )
    except Exception as exc:
        logger.error("Failed to persist stream settings: %s", exc)


# ── Control actions ──────────────────────────────────────────────────────


@router.post("/control/stream/{stream_name}/pause")
async def pause_stream(stream_name: str):
    """Pause a single stream."""
    if _engine_manager:
        engine = _engine_manager.engines.get(stream_name)
        if engine is None:
            return {"error": f"Unknown stream: {stream_name}"}
        engine.stop()
        update_bot_status(stream_name=stream_name, running=False, mode="paused")
        logger.info("Stream '%s' paused via dashboard.", stream_name)
        return {"status": "paused", "stream": stream_name}
    return {"error": "No engine manager"}


@router.post("/control/stream/{stream_name}/resume")
async def resume_stream(stream_name: str):
    """Resume a single paused stream."""
    if _engine_manager:
        import asyncio
        engine = _engine_manager.engines.get(stream_name)
        if engine is None:
            return {"error": f"Unknown stream: {stream_name}"}
        if not engine._running:
            engine._running = True
            asyncio.create_task(engine.run())
            update_bot_status(stream_name=stream_name, running=True, mode="paper")
            logger.info("Stream '%s' resumed via dashboard.", stream_name)
            return {"status": "resumed", "stream": stream_name}
        return {"status": "already_running", "stream": stream_name}
    return {"error": "No engine manager"}


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


# ── Agent Training Tracker ───────────────────────────────────────────────

_TRACKER_PATH = pathlib.Path("data") / "agent_training_tracker.json"
_ITERATE_STATUS_PATH = pathlib.Path("data") / "iterate_status.json"
_ITERATE_STATE_PATH = pathlib.Path("data") / "iterate_state.json"


@router.get("/agent/training-history")
async def agent_training_history():
    """Return all evaluation entries from the tracker file."""
    if _TRACKER_PATH.exists():
        entries = json.loads(_TRACKER_PATH.read_text())
    else:
        entries = []
    return {"entries": entries}


@router.get("/agent/iterate-status")
async def agent_iterate_status():
    """Return the current auto-iterate loop status + state."""
    status = {}
    if _ITERATE_STATUS_PATH.exists():
        status = json.loads(_ITERATE_STATUS_PATH.read_text())

    state = {}
    if _ITERATE_STATE_PATH.exists():
        state = json.loads(_ITERATE_STATE_PATH.read_text())

    return {
        "status": status,
        "state": {
            "iteration": state.get("iteration", 0),
            "best_avg_r": state.get("best_avg_r", None),
            "best_iteration": state.get("best_iteration", 0),
            "nudge_history": state.get("nudge_history", []),
            "env_config": state.get("env_config", {}),
            "reward_config": state.get("reward_config", {}),
        },
    }
