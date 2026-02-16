"""Mean Reversion strategy — buys oversold / sells overbought in ranging markets.

Uses ADX to confirm range-bound conditions, Bollinger Bands + RSI for
entry timing, and S/R zones for structural confirmation.
"""

import logging
import math
from typing import Optional

from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.indicators import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger,
    calculate_rsi,
)
from app.strategy.models import CandleData, EntrySignal, INSTRUMENT_PIP_VALUES
from app.strategy.mr_signals import evaluate_mr_entry
from app.strategy.sr_zones import detect_sr_zones
from app.risk.mr_sl_tp import calculate_mr_sl, calculate_mr_tp

logger = logging.getLogger("forgetrade")


def is_ranging(adx_values: list[float], threshold: float = 25.0) -> bool:
    """Return True when the latest ADX indicates a ranging market.

    A ranging market has ADX below *threshold*.  Returns False if the
    latest ADX value is ``nan`` (insufficient data).
    """
    if not adx_values:
        return False
    latest = adx_values[-1]
    if math.isnan(latest):
        return False
    return latest < threshold


class MeanReversionStrategy:
    """Detects mean-reversion setups on H1 + M15 timeframes.

    Implements ``StrategyProtocol``.

    Flow:
        1. Fetch H1 candles → ADX range check + S/R zone detection.
        2. If not ranging → exit early.
        3. Fetch M15 candles → RSI + Bollinger Bands.
        4. Evaluate MR entry signal (BB touch + RSI extreme + zone).
        5. Calculate SL/TP.
    """

    def __init__(self) -> None:
        self.last_insight: dict = {}

    async def evaluate(self, broker, config) -> Optional[StrategyResult]:
        """Fetch candles, check range, evaluate signal, compute risk.

        Returns ``StrategyResult`` on a valid setup, ``None`` otherwise.
        """
        pip_value = INSTRUMENT_PIP_VALUES.get(config.trade_pair, 0.0001)

        insight: dict = {
            "strategy": "Mean Reversion",
            "pair": config.trade_pair,
            "checks": {},
        }

        # ── 1. Fetch H1 candles → ADX + S/R zones ───────────────────
        h1_raw = await broker.fetch_candles(config.trade_pair, "H1", count=50)
        h1 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h1_raw
        ]

        adx_values = calculate_adx(h1, period=14)
        latest_adx = adx_values[-1] if adx_values and not math.isnan(adx_values[-1]) else None

        insight["adx"] = round(latest_adx, 2) if latest_adx is not None else None
        insight["checks"]["range_detected"] = is_ranging(adx_values, threshold=25.0)

        if not is_ranging(adx_values, threshold=25.0):
            logger.debug(
                "MeanReversion: market trending (ADX %.1f > 25), skipping",
                latest_adx or 0,
            )
            insight["checks"]["at_boundary"] = False
            insight["checks"]["rsi_extreme"] = False
            insight["checks"]["zone_confirmed"] = False
            insight["checks"]["sl_valid"] = False
            insight["checks"]["risk_calculated"] = False
            insight["result"] = "trending"
            self.last_insight = insight
            return None

        # Detect S/R zones from H1 data
        zones = detect_sr_zones(h1)
        insight["checks"]["zone_confirmed"] = len(zones) > 0

        if not zones:
            logger.debug("MeanReversion: no S/R zones detected on H1")
            insight["checks"]["at_boundary"] = False
            insight["checks"]["rsi_extreme"] = False
            insight["checks"]["sl_valid"] = False
            insight["checks"]["risk_calculated"] = False
            insight["result"] = "no_zones"
            self.last_insight = insight
            return None

        # ── 2. Fetch M15 candles → RSI + Bollinger ──────────────────
        m15_raw = await broker.fetch_candles(config.trade_pair, "M15", count=30)
        m15 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in m15_raw
        ]

        rsi_values = calculate_rsi(m15, period=14)
        bb_upper, bb_mid, bb_lower = calculate_bollinger(m15, period=20, std_dev=2.0)

        latest_rsi = rsi_values[-1] if not math.isnan(rsi_values[-1]) else None
        latest_bb_upper = bb_upper[-1] if not math.isnan(bb_upper[-1]) else None
        latest_bb_mid = bb_mid[-1] if not math.isnan(bb_mid[-1]) else None
        latest_bb_lower = bb_lower[-1] if not math.isnan(bb_lower[-1]) else None

        insight["rsi"] = round(latest_rsi, 2) if latest_rsi is not None else None
        insight["bb_upper"] = round(latest_bb_upper, 5) if latest_bb_upper is not None else None
        insight["bb_middle"] = round(latest_bb_mid, 5) if latest_bb_mid is not None else None
        insight["bb_lower"] = round(latest_bb_lower, 5) if latest_bb_lower is not None else None

        current_price = m15[-1].close
        insight["current_price"] = round(current_price, 5)

        # Nearest zone info
        nearest = min(zones, key=lambda z: abs(z.price_level - current_price))
        dist_pips = abs(nearest.price_level - current_price) / pip_value
        insight["nearest_zone"] = {
            "price": round(nearest.price_level, 5),
            "type": nearest.zone_type,
            "distance_pips": round(dist_pips, 1),
        }

        # Check boundary and RSI for insight
        at_boundary = False
        rsi_extreme = False
        if latest_bb_lower is not None and latest_bb_upper is not None:
            at_boundary = current_price <= latest_bb_lower or current_price >= latest_bb_upper
        if latest_rsi is not None:
            rsi_extreme = latest_rsi < 30 or latest_rsi > 70

        insight["checks"]["at_boundary"] = at_boundary
        insight["checks"]["rsi_extreme"] = rsi_extreme

        # ── 3. Evaluate MR entry ────────────────────────────────────
        mr_signal = evaluate_mr_entry(
            m15,
            rsi_values,
            bb_upper,
            bb_lower,
            bb_mid,
            zones,
            pip_value=pip_value,
        )

        if mr_signal is None:
            insight["checks"]["sl_valid"] = False
            insight["checks"]["risk_calculated"] = False
            if not at_boundary:
                insight["result"] = "not_at_boundary"
            elif not rsi_extreme:
                insight["result"] = "rsi_neutral"
            else:
                insight["result"] = "no_zone"
            self.last_insight = insight
            return None

        # ── 4. Risk calculations ────────────────────────────────────
        atr = calculate_atr(h1)

        bb_boundary = (
            mr_signal.bb_level
        )
        sl = calculate_mr_sl(
            mr_signal.entry_price,
            mr_signal.direction,
            mr_signal.nearest_zone.price_level,
            bb_boundary,
            atr,
            pip_value=pip_value,
        )

        if sl is None:
            logger.debug("MeanReversion: SL outside bounds, skipping")
            insight["checks"]["sl_valid"] = False
            insight["checks"]["risk_calculated"] = False
            insight["result"] = "sl_out_of_bounds"
            self.last_insight = insight
            return None

        insight["checks"]["sl_valid"] = True

        tp = calculate_mr_tp(
            mr_signal.entry_price,
            mr_signal.direction,
            latest_bb_mid if latest_bb_mid is not None else mr_signal.entry_price,
        )

        insight["checks"]["risk_calculated"] = True
        insight["signal"] = {
            "direction": mr_signal.direction,
            "entry": round(mr_signal.entry_price, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "rsi": mr_signal.rsi,
            "bb_level": mr_signal.bb_level,
            "zone": round(mr_signal.nearest_zone.price_level, 5),
            "reason": mr_signal.reason,
        }
        insight["atr"] = round(atr, 5)
        insight["result"] = "signal_found"
        self.last_insight = insight

        # Build an EntrySignal for the StrategyResult
        entry_signal = EntrySignal(
            direction=mr_signal.direction,
            entry_price=mr_signal.entry_price,
            sr_zone=mr_signal.nearest_zone,
            candle_time=m15[-1].time,
            reason=mr_signal.reason,
        )

        return StrategyResult(
            signal=entry_signal,
            sl=sl,
            tp=tp,
            atr=atr,
        )
