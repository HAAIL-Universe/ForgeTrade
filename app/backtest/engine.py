"""Backtest engine — replays historical candles through strategy and risk.

Iterates candle data chronologically, evaluating signals and simulating
trades with virtual equity.  No real orders are placed.
"""

from typing import Optional

from app.config import Config
from app.risk.drawdown import DrawdownTracker
from app.risk.position_sizer import calculate_units
from app.risk.sl_tp import calculate_sl, calculate_tp
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData
from app.strategy.session_filter import is_in_session
from app.strategy.signals import evaluate_signal
from app.strategy.sr_zones import detect_sr_zones


class BacktestEngine:
    """Simulates trading on historical candle data.

    Args:
        config: Application configuration (risk %, pair, session hours).
    """

    def __init__(self, config: Config) -> None:
        self._config = config

    # ── Public API ───────────────────────────────────────────────────────

    def run(
        self,
        daily_candles: list[CandleData],
        h4_candles: list[CandleData],
        initial_equity: float = 10_000.0,
    ) -> dict:
        """Execute a full backtest.

        Args:
            daily_candles: Daily candles for S/R zone detection + ATR.
            h4_candles: 4-hour candles iterated chronologically.
            initial_equity: Starting virtual equity.

        Returns:
            Dict with ``trades`` (list of closed-trade dicts),
            ``final_equity``, and ``equity_curve``.
        """
        # Pre-compute zones and ATR from daily data
        zones = detect_sr_zones(daily_candles)
        atr = calculate_atr(daily_candles)

        equity = initial_equity
        tracker = DrawdownTracker(initial_equity, self._config.max_drawdown_pct)
        open_trade: Optional[dict] = None
        closed_trades: list[dict] = []
        equity_curve: list[float] = [initial_equity]

        for i in range(len(h4_candles)):
            candle = h4_candles[i]

            # 1 — Check open trade for SL / TP exit
            if open_trade is not None:
                result = self._check_exit(open_trade, candle)
                if result is not None:
                    exit_price, reason, pnl = result
                    open_trade["exit_price"] = exit_price
                    open_trade["exit_reason"] = reason
                    open_trade["pnl"] = pnl
                    open_trade["closed_at"] = candle.time
                    equity += pnl
                    tracker.update(equity)
                    closed_trades.append(open_trade)
                    open_trade = None
                    equity_curve.append(equity)

            # 2 — Skip entry if circuit breaker active
            if tracker.circuit_breaker_active:
                continue

            # 3 — Skip entry if already in a trade
            if open_trade is not None:
                continue

            # 4 — Evaluate signal using a sliding window of recent 4H candles
            window_start = max(0, i - 19)
            window = h4_candles[window_start : i + 1]
            signal = evaluate_signal(window, zones)

            if signal is None:
                continue

            # 5 — Risk calculations
            sl = calculate_sl(
                signal.entry_price, signal.direction,
                signal.sr_zone.price_level, atr,
            )
            tp = calculate_tp(signal.entry_price, signal.direction, sl, zones)
            sl_pips = abs(signal.entry_price - sl) / 0.0001
            units = calculate_units(
                equity, self._config.risk_per_trade_pct, sl_pips,
            )

            open_trade = {
                "mode": "backtest",
                "direction": signal.direction,
                "pair": self._config.trade_pair,
                "entry_price": signal.entry_price,
                "sl": round(sl, 5),
                "tp": round(tp, 5),
                "units": units,
                "sr_zone_price": signal.sr_zone.price_level,
                "sr_zone_type": signal.sr_zone.zone_type,
                "entry_reason": signal.reason,
                "opened_at": candle.time,
                "exit_price": None,
                "exit_reason": None,
                "pnl": None,
                "closed_at": None,
            }

        # Close any remaining position at last candle close
        if open_trade is not None and h4_candles:
            last = h4_candles[-1]
            pnl = self._mark_to_market(open_trade, last.close)
            open_trade["exit_price"] = last.close
            open_trade["exit_reason"] = "end_of_data"
            open_trade["pnl"] = pnl
            open_trade["closed_at"] = last.time
            equity += pnl
            tracker.update(equity)
            closed_trades.append(open_trade)
            equity_curve.append(equity)

        return {
            "trades": closed_trades,
            "final_equity": equity,
            "equity_curve": equity_curve,
        }

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _check_exit(
        trade: dict, candle: CandleData,
    ) -> Optional[tuple[float, str, float]]:
        """Check if *candle* triggers an SL or TP exit.

        Returns ``(exit_price, reason, pnl)`` or ``None``.
        When both are hit in the same candle, SL is assumed first
        (conservative).
        """
        direction = trade["direction"]
        sl = trade["sl"]
        tp = trade["tp"]

        if direction == "buy":
            sl_hit = candle.low <= sl
            tp_hit = candle.high >= tp
        else:
            sl_hit = candle.high >= sl
            tp_hit = candle.low <= tp

        # Worst-case precedence when both occur in one bar
        if sl_hit and tp_hit:
            tp_hit = False

        if sl_hit:
            return (
                sl,
                "SL hit",
                BacktestEngine._calc_pnl(trade, sl),
            )
        if tp_hit:
            return (
                tp,
                "TP hit",
                BacktestEngine._calc_pnl(trade, tp),
            )
        return None

    @staticmethod
    def _calc_pnl(trade: dict, exit_price: float) -> float:
        """Compute P&L for a trade exiting at *exit_price*."""
        if trade["direction"] == "buy":
            return (exit_price - trade["entry_price"]) * trade["units"]
        return (trade["entry_price"] - exit_price) * trade["units"]

    @staticmethod
    def _mark_to_market(trade: dict, current_price: float) -> float:
        """Unrealised P&L at *current_price*."""
        return BacktestEngine._calc_pnl(trade, current_price)
