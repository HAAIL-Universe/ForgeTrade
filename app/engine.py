"""ForgeTrade — Trading engine (orchestration loop).

Connects strategy, risk management, and broker into a single polling loop.
Strategy evaluates → engine handles position sizing + order placement.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.api.routers import update_bot_status, update_pending_signal
from app.broker.models import OrderRequest
from app.broker.oanda_client import OandaClient
from app.config import Config
from app.risk.drawdown import DrawdownTracker
from app.risk.position_sizer import calculate_units
from app.strategy.base import StrategyProtocol
from app.strategy.models import INSTRUMENT_PIP_VALUES
from app.strategy.session_filter import is_in_session

logger = logging.getLogger("forgetrade")


class TradingEngine:
    """Orchestrates one evaluation-and-execution cycle per call.

    Args:
        config: Application configuration.
        broker: An ``OandaClient`` (or compatible duck-type / mock).
        strategy: A strategy implementing ``StrategyProtocol``.
    """

    def __init__(
        self,
        config: Config,
        broker: OandaClient,
        strategy: Optional[StrategyProtocol] = None,
    ) -> None:
        self._config = config
        self._broker = broker
        self._strategy = strategy
        self._drawdown: Optional[DrawdownTracker] = None
        self._running: bool = False
        self._cycle_count: int = 0

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Fetch initial account state and set up the drawdown tracker."""
        summary = await self._broker.get_account_summary()
        self._drawdown = DrawdownTracker(
            initial_equity=summary.equity,
            max_drawdown_pct=self._config.max_drawdown_pct,
        )
        self._running = True

    def stop(self) -> None:
        """Signal the engine to stop after the current cycle."""
        self._running = False

    # ── Polling loop ─────────────────────────────────────────────────────

    async def run(
        self,
        poll_interval: int = 300,
        max_cycles: int = 0,
    ) -> list[dict]:
        """Run the trading loop until stopped.

        Args:
            poll_interval: Seconds between cycles.
            max_cycles: Stop after this many cycles (0 = unlimited).

        Returns:
            List of per-cycle result dicts.
        """
        results: list[dict] = []
        cycle = 0

        while self._running:
            cycle += 1
            self._cycle_count += 1
            try:
                result = await self.run_once()
                results.append(result)
                logger.info("Cycle %d: %s", cycle, result.get("action", "unknown"))
                update_bot_status(
                    cycle_count=self._cycle_count,
                    last_cycle_at=datetime.now(timezone.utc).isoformat(),
                )
            except Exception as exc:
                logger.error("Cycle %d error: %s", cycle, exc)
                results.append({"action": "error", "reason": str(exc)})

            if max_cycles > 0 and cycle >= max_cycles:
                break

            # Interruptible sleep — checks _running every second
            for _ in range(poll_interval):
                if not self._running:
                    break
                await asyncio.sleep(1)

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
            return {"action": "halted", "reason": "circuit_breaker"}

        # 2 ── Session filter
        if not is_in_session(
            utc_now.hour,
            self._config.session_start_utc,
            self._config.session_end_utc,
        ):
            return {"action": "skipped", "reason": "outside_session"}

        # 3 ── Strategy evaluation (delegates to pluggable strategy)
        if self._strategy is None:
            return {"action": "skipped", "reason": "no_strategy"}

        result = await self._strategy.evaluate(self._broker, self._config)
        if result is None:
            update_pending_signal({
                "pair": self._config.trade_pair,
                "direction": None,
                "zone_price": None,
                "zone_type": None,
                "reason": "No signal from strategy",
                "status": "no_signal",
                "evaluated_at": utc_now.isoformat(),
                "stream_name": "default",
            })
            return {"action": "skipped", "reason": "no_signal"}

        signal = result.signal
        sl = result.sl
        tp = result.tp

        # Update watchlist with the signal
        update_pending_signal({
            "pair": self._config.trade_pair,
            "direction": signal.direction,
            "zone_price": signal.sr_zone.price_level,
            "zone_type": signal.sr_zone.zone_type,
            "reason": signal.reason,
            "status": "watching",
            "evaluated_at": utc_now.isoformat(),
            "stream_name": "default",
        })

        # 4 ── Account state + position sizing
        summary = await self._broker.get_account_summary()
        if self._drawdown:
            self._drawdown.update(summary.equity)
            if self._drawdown.circuit_breaker_active:
                return {"action": "halted", "reason": "circuit_breaker"}

        pip_value = INSTRUMENT_PIP_VALUES.get(self._config.trade_pair, 0.0001)
        sl_pips = abs(signal.entry_price - sl) / pip_value
        units = calculate_units(
            summary.equity,
            self._config.risk_per_trade_pct,
            sl_pips,
        )
        if signal.direction == "sell":
            units = -units

        # 5 ── Place order
        price_digits = 2 if "XAU" in self._config.trade_pair else 5
        order_req = OrderRequest(
            instrument=self._config.trade_pair,
            units=units,
            stop_loss_price=round(sl, price_digits),
            take_profit_price=round(tp, price_digits),
        )
        order_resp = await self._broker.place_order(order_req)

        # Update watchlist status to "entered"
        update_pending_signal({
            "pair": self._config.trade_pair,
            "direction": signal.direction,
            "zone_price": signal.sr_zone.price_level,
            "zone_type": signal.sr_zone.zone_type,
            "reason": signal.reason,
            "status": "entered",
            "evaluated_at": utc_now.isoformat(),
            "stream_name": "default",
        })
        update_bot_status(
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
