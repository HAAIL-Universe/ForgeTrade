"""ForgeTrade — Trading engine (orchestration loop).

Connects strategy, risk management, and broker into a single polling loop.
Fetch candles → evaluate signal → check risk → place order.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from app.broker.models import OrderRequest
from app.broker.oanda_client import OandaClient
from app.config import Config
from app.risk.drawdown import DrawdownTracker
from app.risk.position_sizer import calculate_units
from app.risk.sl_tp import calculate_sl, calculate_tp
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData
from app.strategy.session_filter import is_in_session
from app.strategy.signals import evaluate_signal
from app.strategy.sr_zones import detect_sr_zones

logger = logging.getLogger("forgetrade")


class TradingEngine:
    """Orchestrates one evaluation-and-execution cycle per call.

    Args:
        config: Application configuration.
        broker: An ``OandaClient`` (or compatible duck-type / mock).
    """

    def __init__(self, config: Config, broker: OandaClient) -> None:
        self._config = config
        self._broker = broker
        self._drawdown: Optional[DrawdownTracker] = None
        self._running: bool = False

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
            try:
                result = await self.run_once()
                results.append(result)
                logger.info("Cycle %d: %s", cycle, result.get("action", "unknown"))
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

        # 3 ── Fetch daily candles → detect S/R zones
        daily_raw = await self._broker.fetch_candles(
            self._config.trade_pair, "D", count=50,
        )
        daily = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in daily_raw
        ]
        zones = detect_sr_zones(daily)
        if not zones:
            return {"action": "skipped", "reason": "no_zones"}

        # 4 ── Fetch 4H candles → evaluate signal
        h4_raw = await self._broker.fetch_candles(
            self._config.trade_pair, "H4", count=20,
        )
        h4 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h4_raw
        ]
        signal = evaluate_signal(h4, zones)
        if signal is None:
            return {"action": "skipped", "reason": "no_signal"}

        # 5 ── Risk calculations
        atr = calculate_atr(daily)
        sl = calculate_sl(
            signal.entry_price,
            signal.direction,
            signal.sr_zone.price_level,
            atr,
        )
        tp = calculate_tp(signal.entry_price, signal.direction, sl, zones)

        # 6 ── Account state + position sizing
        summary = await self._broker.get_account_summary()
        if self._drawdown:
            self._drawdown.update(summary.equity)
            # Re-check circuit breaker after equity update
            if self._drawdown.circuit_breaker_active:
                return {"action": "halted", "reason": "circuit_breaker"}

        sl_pips = abs(signal.entry_price - sl) / 0.0001
        units = calculate_units(
            summary.equity,
            self._config.risk_per_trade_pct,
            sl_pips,
        )
        if signal.direction == "sell":
            units = -units

        # 7 ── Place order
        order_req = OrderRequest(
            instrument=self._config.trade_pair,
            units=units,
            stop_loss_price=round(sl, 5),
            take_profit_price=round(tp, 5),
        )
        order_resp = await self._broker.place_order(order_req)

        return {
            "action": "order_placed",
            "order_id": order_resp.order_id,
            "direction": signal.direction,
            "units": units,
            "entry": signal.entry_price,
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "reason": signal.reason,
        }
