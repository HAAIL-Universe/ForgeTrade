"""ForgeTrade — Trading engine (orchestration loop).

Connects strategy, risk management, and broker into a single polling loop.
Strategy evaluates → engine handles position sizing + order placement.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.api.routers import update_bot_status, update_pending_signal, update_strategy_insight
from app.broker.models import OrderRequest
from app.broker.oanda_client import OandaClient
from app.config import Config
from app.models.stream_config import StreamConfig
from app.risk.drawdown import DrawdownTracker
from app.risk.position_sizer import calculate_units
from app.strategy.base import StrategyProtocol
from app.strategy.models import INSTRUMENT_PIP_VALUES
from app.strategy.session_filter import is_in_session

logger = logging.getLogger("forgetrade")


class _EngineConfig:
    """Lightweight wrapper that overrides ``trade_pair`` per-stream.

    Delegates every attribute to the underlying global ``Config``,
    except ``trade_pair`` which is set to the stream's instrument.
    """

    def __init__(self, config: Config, instrument: str) -> None:
        object.__setattr__(self, "_inner", config)
        object.__setattr__(self, "trade_pair", instrument)

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
            for _ in range(poll_interval):
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

        # 1 ── Circuit breaker
        if self._drawdown and self._drawdown.circuit_breaker_active:
            update_strategy_insight(self.stream_name, {
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
            return {"action": "halted", "reason": "circuit_breaker"}

        # 2 ── Session filter
        if not is_in_session(
            utc_now.hour,
            self._session_start,
            self._session_end,
        ):
            update_strategy_insight(self.stream_name, {
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
            return {"action": "skipped", "reason": "outside_session"}

        # 3 ── Strategy evaluation (delegates to pluggable strategy)
        if self._strategy is None:
            return {"action": "skipped", "reason": "no_strategy"}

        # Wrap config so strategy sees this stream's instrument as trade_pair
        engine_config = _EngineConfig(self._config, self.instrument)
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
            update_strategy_insight(self.stream_name, insight)

        if result is None:
            update_pending_signal({
                "pair": self.instrument,
                "direction": None,
                "zone_price": None,
                "zone_type": None,
                "reason": "No signal from strategy",
                "status": "no_signal",
                "evaluated_at": utc_now.isoformat(),
                "stream_name": self.stream_name,
            })
            return {"action": "skipped", "reason": "no_signal"}

        signal = result.signal
        sl = result.sl
        tp = result.tp

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
