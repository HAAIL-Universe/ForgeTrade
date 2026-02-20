"""ForgeTrade — Trading engine (orchestration loop).

Connects strategy, risk management, and broker into a single polling loop.
Strategy evaluates → engine handles position sizing + order placement.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.api.routers import update_bot_status, update_pending_signal, update_strategy_insight, push_rl_decision
from app.broker.models import OrderRequest
from app.broker.oanda_client import OandaClient
from app.config import Config
from app.models.stream_config import StreamConfig
from app.risk.drawdown import DrawdownTracker
from app.risk.position_sizer import calculate_units
from app.strategy.base import StrategyProtocol
from app.strategy.models import INSTRUMENT_PIP_VALUES
from app.strategy.session_filter import is_in_session

# ForgeAgent RL filter (optional — only loaded when configured)
try:
    from app.rl.filter import RLTradeFilter, ShadowLogger
    from app.rl.features import ForgeStateBuilder, AccountSnapshot
    _RL_AVAILABLE = True
except ImportError:
    _RL_AVAILABLE = False

logger = logging.getLogger("forgetrade")


class _EngineConfig:
    """Lightweight wrapper that overrides ``trade_pair`` per-stream.

    Delegates every attribute to the underlying global ``Config``,
    except ``trade_pair`` which is set to the stream's instrument,
    and ``rr_ratio`` which is set from the stream config.
    """

    def __init__(self, config: Config, instrument: str, rr_ratio: float | None = None) -> None:
        object.__setattr__(self, "_inner", config)
        object.__setattr__(self, "trade_pair", instrument)
        object.__setattr__(self, "rr_ratio", rr_ratio)

    def __getattr__(self, name: str):
        return getattr(object.__getattribute__(self, "_inner"), name)


class TradingEngine:
    """Orchestrates one evaluation-and-execution cycle per call.

    Args:
        config: Application configuration (global settings).
        broker: An ``OandaClient`` (or compatible duck-type / mock).
        strategy: A strategy implementing ``StrategyProtocol``.
        stream_config: Per-stream settings. If None, uses global config.
    """

    def __init__(
        self,
        config: Config,
        broker: OandaClient,
        strategy: Optional[StrategyProtocol] = None,
        stream_config: Optional[StreamConfig] = None,
    ) -> None:
        self._config = config
        self._broker = broker
        self._strategy = strategy
        self._stream_config = stream_config
        self._drawdown: Optional[DrawdownTracker] = None
        self._running: bool = False
        self._cycle_count: int = 0

        # ForgeAgent RL filter
        self._rl_filter: Optional[object] = None
        self._rl_shadow: Optional[object] = None
        self._rl_state_builder: Optional[object] = None
        self._rl_mode: str = "disabled"
        self._init_rl_filter()

    def _init_rl_filter(self) -> None:
        """Initialise ForgeAgent RL filter if configured for this stream."""
        if not _RL_AVAILABLE:
            return
        if not self._stream_config or not self._stream_config.rl_filter:
            return

        rl_cfg = self._stream_config.rl_filter
        mode = rl_cfg.get("mode", "disabled")
        if mode == "disabled":
            return

        model_path = rl_cfg.get("model_path", "")
        threshold = rl_cfg.get("confidence_threshold", 0.6)

        try:
            self._rl_filter = RLTradeFilter(model_path, threshold)
            self._rl_state_builder = ForgeStateBuilder()
            self._rl_mode = mode

            if mode == "shadow" and rl_cfg.get("log_decisions", True):
                self._rl_shadow = ShadowLogger()

            logger.info(
                "Stream '%s' — ForgeAgent loaded in %s mode (threshold=%.2f)",
                self.stream_name, mode, threshold,
            )
        except Exception as exc:
            logger.warning(
                "Stream '%s' — ForgeAgent failed to load: %s (continuing without RL filter)",
                self.stream_name, exc,
            )
            self._rl_mode = "disabled"

    @property
    def stream_name(self) -> str:
        """Return the name of this engine's stream."""
        if self._stream_config:
            return self._stream_config.name
        return "default"

    @property
    def instrument(self) -> str:
        """Return the instrument this engine trades."""
        if self._stream_config:
            return self._stream_config.instrument
        return self._config.trade_pair

    @property
    def _session_start(self) -> int:
        if self._stream_config:
            return self._stream_config.session_start_utc
        return self._config.session_start_utc

    @property
    def _session_end(self) -> int:
        if self._stream_config:
            return self._stream_config.session_end_utc
        return self._config.session_end_utc

    @property
    def _risk_pct(self) -> float:
        if self._stream_config:
            return self._stream_config.risk_per_trade_pct
        return self._config.risk_per_trade_pct

    @property
    def _rr_ratio(self) -> float | None:
        """Per-stream R:R override, or None for strategy default."""
        if self._stream_config:
            return self._stream_config.rr_ratio
        return None

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Fetch initial account state and set up the drawdown tracker."""
        try:
            summary = await self._broker.get_account_summary()
            self._drawdown = DrawdownTracker(
                initial_equity=summary.equity,
                max_drawdown_pct=self._config.max_drawdown_pct,
            )
            update_bot_status(
                stream_name=self.stream_name,
                equity=summary.equity,
                balance=summary.balance,
                running=True,
                started_at=datetime.now(timezone.utc).isoformat(),
                strategy=(
                    self._stream_config.strategy
                    if self._stream_config else None
                ),
            )
        except Exception as exc:
            logger.error(
                "Stream '%s' — failed to initialise (OANDA unreachable?): %s",
                self.stream_name, exc,
            )
            # Create a dummy drawdown tracker so the loop can still run
            self._drawdown = DrawdownTracker(
                initial_equity=0.0,
                max_drawdown_pct=self._config.max_drawdown_pct,
            )
        self._running = True

    def stop(self) -> None:
        """Signal the engine to stop after the current cycle."""
        self._running = False

    # ── Polling loop ─────────────────────────────────────────────────────

    async def run(
        self,
        poll_interval: int | None = None,
        max_cycles: int = 0,
    ) -> list[dict]:
        """Run the trading loop until stopped.

        Args:
            poll_interval: Seconds between cycles. Defaults to stream config
                           or 300.
            max_cycles: Stop after this many cycles (0 = unlimited).

        Returns:
            List of per-cycle result dicts.
        """
        if poll_interval is None:
            poll_interval = (
                self._stream_config.poll_interval_seconds
                if self._stream_config
                else 300
            )
        results: list[dict] = []
        cycle = 0

        while self._running:
            cycle += 1
            self._cycle_count += 1
            try:
                result = await self.run_once()
                results.append(result)
                logger.info("Cycle %d: %s", cycle, result.get("action", "unknown"))
                # Refresh account data for the dashboard
                try:
                    acct = await self._broker.get_account_summary()
                    dd_pct = 0.0
                    if self._drawdown:
                        self._drawdown.update(acct.equity)
                        dd_pct = self._drawdown.drawdown_pct
                    update_bot_status(
                        stream_name=self.stream_name,
                        running=True,
                        pair=self.instrument,
                        cycle_count=self._cycle_count,
                        last_cycle_at=datetime.now(timezone.utc).isoformat(),
                        equity=acct.equity,
                        balance=acct.balance,
                        peak_equity=self._drawdown.peak if self._drawdown else None,
                        drawdown_pct=round(dd_pct, 2),
                        circuit_breaker_active=(
                            self._drawdown.circuit_breaker_active
                            if self._drawdown else False
                        ),
                        open_positions=acct.open_position_count,
                        last_signal_check=datetime.now(timezone.utc).isoformat(),
                    )
                except Exception:
                    update_bot_status(
                        stream_name=self.stream_name,
                        cycle_count=self._cycle_count,
                        last_cycle_at=datetime.now(timezone.utc).isoformat(),
                    )
            except Exception as exc:
                logger.error("Cycle %d error: %s", cycle, exc)
                results.append({"action": "error", "reason": str(exc)})
                # Push error into signal log so it's visible on dashboard
                update_pending_signal({
                    "pair": self.instrument,
                    "direction": "—",
                    "zone_price": None,
                    "reason": f"ERROR: {exc}",
                    "status": "error",
                    "evaluated_at": datetime.now(timezone.utc).isoformat(),
                    "stream_name": self.stream_name,
                })

            if max_cycles > 0 and cycle >= max_cycles:
                break

            # Interruptible sleep — checks _running every second
            # Re-read poll interval each cycle so dashboard changes take
            # effect without restarting the engine.
            current_interval = (
                self._stream_config.poll_interval_seconds
                if self._stream_config
                else poll_interval
            )
            for _ in range(current_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

        update_bot_status(stream_name=self.stream_name, running=False)
        return results

    # ── Single cycle ─────────────────────────────────────────────────────

    async def run_once(self, utc_now: Optional[datetime] = None) -> dict:
        """Execute one trading cycle.

        Returns a dict describing the action taken:

        - ``{"action": "halted", "reason": "circuit_breaker"}``
        - ``{"action": "skipped", "reason": "..."}``
        - ``{"action": "order_placed", ...}``

        Args:
            utc_now: Current UTC datetime.  Defaults to ``datetime.now(UTC)``.
                     Accepting it as a parameter makes the engine testable
                     without mocking ``datetime``.
        """
        if utc_now is None:
            utc_now = datetime.now(timezone.utc)

        # 0 ── Always push ForgeAgent mode so the UI always shows agent status
        _rl_base = {"rl_mode": self._rl_mode}

        # 1 ── Circuit breaker
        if self._drawdown and self._drawdown.circuit_breaker_active:
            update_strategy_insight(self.stream_name, {
                **_rl_base,
                "strategy": "—",
                "pair": self.instrument,
                "checks": {
                    "circuit_breaker_clear": False,
                    "in_session": False,
                    "zones_detected": False,
                    "zone_proximity": False,
                    "rejection_wick": False,
                    "risk_calculated": False,
                },
                "result": "circuit_breaker",
                "evaluated_at": utc_now.isoformat(),
            })
            update_pending_signal({
                "pair": self.instrument,
                "direction": None,
                "reason": "Circuit breaker active",
                "status": "halted",
                "evaluated_at": utc_now.isoformat(),
                "stream_name": self.stream_name,
            })
            return {"action": "halted", "reason": "circuit_breaker"}

        # 2 ── Session filter
        if not is_in_session(
            utc_now.hour,
            self._session_start,
            self._session_end,
        ):
            update_strategy_insight(self.stream_name, {
                **_rl_base,
                "strategy": "—",
                "pair": self.instrument,
                "checks": {
                    "circuit_breaker_clear": True,
                    "in_session": False,
                    "zones_detected": False,
                    "zone_proximity": False,
                    "rejection_wick": False,
                    "risk_calculated": False,
                },
                "result": "outside_session",
                "evaluated_at": utc_now.isoformat(),
            })
            update_pending_signal({
                "pair": self.instrument,
                "direction": None,
                "reason": "Outside session window",
                "status": "skipped",
                "evaluated_at": utc_now.isoformat(),
                "stream_name": self.stream_name,
            })
            return {"action": "skipped", "reason": "outside_session"}

        # 2b ── Session-end buffer for scalp strategies
        #       Scalps need time to play out — skip if too close to session end.
        #       Skip this check for 24h sessions (0-24) — market is continuous during the week.
        buffer_min = getattr(self._strategy, "SESSION_END_BUFFER_MIN", 0) if self._strategy else 0
        is_24h_session = (self._session_start == 0 and self._session_end == 24)
        if buffer_min and isinstance(buffer_min, (int, float)) and buffer_min > 0 and not is_24h_session:
            session_end_hour = self._session_end
            # Minutes until session closes
            mins_until_close = (session_end_hour - utc_now.hour - 1) * 60 + (60 - utc_now.minute)
            if mins_until_close <= buffer_min:
                update_strategy_insight(self.stream_name, {
                    **_rl_base,
                    "strategy": "Momentum Scalp",
                    "pair": self.instrument,
                    "checks": {
                        "circuit_breaker_clear": True,
                        "in_session": True,
                        "session_end_buffer": False,
                    },
                    "result": "session_ending_soon",
                    "mins_until_close": mins_until_close,
                    "buffer_min": buffer_min,
                    "evaluated_at": utc_now.isoformat(),
                })
                update_pending_signal({
                    "pair": self.instrument,
                    "direction": None,
                    "reason": f"Session ending in {mins_until_close} min",
                    "status": "skipped",
                    "evaluated_at": utc_now.isoformat(),
                    "stream_name": self.stream_name,
                })
                return {"action": "skipped", "reason": "session_ending_soon"}

        # 3 ── Strategy evaluation (delegates to pluggable strategy)
        if self._strategy is None:
            return {"action": "skipped", "reason": "no_strategy"}

        # Wrap config so strategy sees this stream's instrument + rr_ratio
        engine_config = _EngineConfig(self._config, self.instrument, rr_ratio=self._rr_ratio)
        result = await self._strategy.evaluate(self._broker, engine_config)

        # Push strategy insight data to the dashboard (if strategy supports it)
        if hasattr(self._strategy, "last_insight") and isinstance(self._strategy.last_insight, dict):
            insight = self._strategy.last_insight.copy()
            insight["evaluated_at"] = utc_now.isoformat()
            # Override pair with the engine's instrument (strategy may read
            # the global config.trade_pair which is always EUR_USD)
            insight["pair"] = self.instrument
            # Add engine-level checks
            insight.setdefault("checks", {})
            insight["checks"]["in_session"] = True  # We got past check 2
            insight["checks"]["circuit_breaker_clear"] = True  # Got past check 1
            # Merge ForgeAgent mode so UI always reflects current state
            insight.update(_rl_base)
            update_strategy_insight(self.stream_name, insight)

        if result is None:
            # Forward the strategy's specific skip reason if available
            skip_reason = "No signal from strategy"
            if (
                hasattr(self._strategy, "last_insight")
                and isinstance(self._strategy.last_insight, dict)
                and self._strategy.last_insight.get("result")
            ):
                reason_slug = self._strategy.last_insight["result"]
                _REASON_LABELS = {
                    "no_bias": "No directional bias",
                    "low_volatility": "Low volatility (ATR too low)",
                    "spread_too_wide": "Spread too wide",
                    "no_pullback": "No pullback to EMA",
                    "no_confirmation": "No confirmation pattern",
                }
                skip_reason = _REASON_LABELS.get(reason_slug, reason_slug.replace("_", " ").capitalize())
            update_pending_signal({
                "pair": self.instrument,
                "direction": None,
                "zone_price": None,
                "zone_type": None,
                "reason": skip_reason,
                "status": "skipped",
                "evaluated_at": utc_now.isoformat(),
                "stream_name": self.stream_name,
            })
            return {"action": "skipped", "reason": "no_signal"}

        signal = result.signal
        sl = result.sl
        tp = result.tp

        # ── ForgeAgent RL filter ─────────────────────────────────────
        if self._rl_filter is not None and self._rl_mode in ("shadow", "active"):
            try:
                # Build state vector from candle data cached by strategy
                m5_raw = await self._broker.fetch_candles(self.instrument, "M5", count=100)
                m1_raw = await self._broker.fetch_candles(self.instrument, "M1", count=20)
                h1_raw = await self._broker.fetch_candles(self.instrument, "H1", count=50)
                m15_raw = await self._broker.fetch_candles(self.instrument, "M15", count=30)

                from app.strategy.models import CandleData as _CD
                _to_cd = lambda cs: [_CD(c.time, c.open, c.high, c.low, c.close, c.volume) for c in cs]

                dd_pct = self._drawdown.drawdown_pct if self._drawdown else 0.0
                account_snap = AccountSnapshot(
                    drawdown_pct=dd_pct,
                    max_drawdown_pct=self._config.max_drawdown_pct,
                )

                state = self._rl_state_builder.build(
                    m5_candles=_to_cd(m5_raw),
                    m1_candles=_to_cd(m1_raw),
                    h1_candles=_to_cd(h1_raw),
                    m15_candles=_to_cd(m15_raw),
                    account=account_snap,
                    pip_value=INSTRUMENT_PIP_VALUES.get(self.instrument, 0.01),
                )
                state_arr = state.to_array()

                rl_action, rl_conf = self._rl_filter.assess(state_arr)

                # Shadow logging
                if self._rl_shadow:
                    self._rl_shadow.log(
                        timestamp=utc_now.isoformat(),
                        instrument=self.instrument,
                        direction=signal.direction,
                        entry_price=signal.entry_price,
                        action=rl_action,
                        confidence=rl_conf,
                    )

                # Push decision to dashboard ring buffer (both shadow + active)
                push_rl_decision({
                    "timestamp": utc_now.isoformat(),
                    "instrument": self.instrument,
                    "direction": signal.direction,
                    "entry_price": round(signal.entry_price, 2),
                    "action": "TAKE" if rl_action == 1 else "VETO",
                    "confidence": round(rl_conf, 4),
                    "mode": self._rl_mode,
                })

                # Update insight with latest decision for both modes
                update_strategy_insight(self.stream_name, {
                    "rl_filter": "approved" if rl_action == 1 else "vetoed",
                    "rl_confidence": round(rl_conf, 3),
                    "rl_assessed_at": utc_now.isoformat(),
                })

                # Active mode: veto low-confidence signals
                if self._rl_mode == "active" and rl_action == 0:
                    logger.info(
                        "ForgeAgent VETOED %s %s signal (confidence=%.2f)",
                        signal.direction, self.instrument, rl_conf,
                    )
                    update_pending_signal({
                        "pair": self.instrument,
                        "direction": signal.direction,
                        "reason": f"ForgeAgent vetoed (conf={rl_conf:.2f})",
                        "status": "skipped",
                        "evaluated_at": utc_now.isoformat(),
                        "stream_name": self.stream_name,
                    })
                    return {"action": "skipped", "reason": "rl_veto", "confidence": rl_conf}

                # Log approval
                if self._rl_mode == "active":
                    logger.info(
                        "ForgeAgent APPROVED %s %s signal (confidence=%.2f)",
                        signal.direction, self.instrument, rl_conf,
                    )

            except Exception as exc:
                logger.warning("ForgeAgent error (proceeding without filter): %s", exc)

        # Update watchlist with the signal
        update_pending_signal({
            "pair": self.instrument,
            "direction": signal.direction,
            "zone_price": signal.sr_zone.price_level,
            "zone_type": signal.sr_zone.zone_type,
            "reason": signal.reason,
            "status": "watching",
            "evaluated_at": utc_now.isoformat(),
            "stream_name": self.stream_name,
        })
        update_bot_status(
            stream_name=self.stream_name,
            last_signal_time=utc_now.isoformat(),
        )

        # 4 ── Account state + position sizing
        summary = await self._broker.get_account_summary()
        if self._drawdown:
            self._drawdown.update(summary.equity)
            if self._drawdown.circuit_breaker_active:
                return {"action": "halted", "reason": "circuit_breaker"}

        pip_value = INSTRUMENT_PIP_VALUES.get(self.instrument, 0.0001)
        sl_pips = abs(signal.entry_price - sl) / pip_value
        units = calculate_units(
            summary.equity,
            self._risk_pct,
            sl_pips,
            pip_value=pip_value,
        )
        # OANDA expects integer units for most instruments
        units = int(units)
        if units == 0:
            units = 1  # minimum 1 unit
        if signal.direction == "sell":
            units = -units

        # 4b ── Position count guard
        if self._stream_config and self._stream_config.max_concurrent_positions > 0:
            try:
                open_positions = await self._broker.list_open_positions()
                instrument_positions = sum(
                    1 for p in open_positions
                    if p.instrument == self.instrument
                )
                if instrument_positions >= self._stream_config.max_concurrent_positions:
                    update_pending_signal({
                        "pair": self.instrument,
                        "direction": signal.direction,
                        "reason": f"Max positions ({self._stream_config.max_concurrent_positions}) reached",
                        "status": "skipped",
                        "evaluated_at": utc_now.isoformat(),
                        "stream_name": self.stream_name,
                    })
                    return {
                        "action": "skipped",
                        "reason": "max_concurrent_positions",
                    }
            except Exception:
                pass  # If we can't check, proceed cautiously

        # 5 ── Place order
        price_digits = 2 if "XAU" in self.instrument else 5
        order_req = OrderRequest(
            instrument=self.instrument,
            units=units,
            stop_loss_price=round(sl, price_digits),
            take_profit_price=round(tp, price_digits),
        )
        order_resp = await self._broker.place_order(order_req)

        # Update watchlist status to "entered"
        update_pending_signal({
            "pair": self.instrument,
            "direction": signal.direction,
            "zone_price": signal.sr_zone.price_level,
            "zone_type": signal.sr_zone.zone_type,
            "reason": signal.reason,
            "status": "entered",
            "evaluated_at": utc_now.isoformat(),
            "stream_name": self.stream_name,
        })
        update_bot_status(
            stream_name=self.stream_name,
            last_order_time=utc_now.isoformat(),
        )

        return {
            "action": "order_placed",
            "order_id": order_resp.order_id,
            "direction": signal.direction,
            "units": units,
            "entry": signal.entry_price,
            "sl": round(sl, price_digits),
            "tp": round(tp, price_digits),
            "reason": signal.reason,
        }
