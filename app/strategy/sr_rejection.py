"""S/R Rejection Wick strategy — extracted from the original engine.

Identifies support/resistance zones on Daily candles, then looks for
rejection wicks on H4 candles near those zones.
"""

import logging
from typing import Optional

from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData
from app.strategy.signals import (
    evaluate_signal,
    _candle_touches_zone,
    _is_rejection_wick_buy,
    _is_rejection_wick_sell,
)
from app.strategy.sr_zones import detect_sr_zones
from app.risk.sl_tp import calculate_sl, calculate_tp

logger = logging.getLogger("forgetrade")


class SRRejectionStrategy:
    """Detects S/R rejection-wick setups on D + H4 timeframes.

    Implements ``StrategyProtocol``.
    """

    def __init__(self) -> None:
        self.last_insight: dict = {}

    async def evaluate(self, broker, config) -> Optional[StrategyResult]:
        """Fetch candles, detect zones, evaluate signal, compute SL/TP.

        Returns ``StrategyResult`` on a valid setup, ``None`` otherwise.
        Also populates ``self.last_insight`` with analysis data for the dashboard.
        """
        insight: dict = {
            "strategy": "sr_rejection",
            "pair": config.trade_pair,
            "checks": {},
        }

        # 1 ── Fetch daily candles → detect S/R zones
        daily_raw = await broker.fetch_candles(
            config.trade_pair, "D", count=50,
        )
        daily = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in daily_raw
        ]
        zones = detect_sr_zones(daily)

        support_zones = [z for z in zones if z.zone_type == "support"]
        resistance_zones = [z for z in zones if z.zone_type == "resistance"]

        insight["zones"] = {
            "total": len(zones),
            "support": [
                {"price": round(z.price_level, 5), "touches": z.strength}
                for z in support_zones
            ],
            "resistance": [
                {"price": round(z.price_level, 5), "touches": z.strength}
                for z in resistance_zones
            ],
        }
        insight["checks"]["zones_detected"] = len(zones) > 0

        if not zones:
            logger.debug("SRRejection: no zones detected")
            insight["checks"]["zone_proximity"] = False
            insight["checks"]["rejection_wick"] = False
            insight["checks"]["risk_calculated"] = False
            insight["result"] = "no_zones"
            self.last_insight = insight
            return None

        # 2 ── Fetch 4H candles → evaluate signal
        h4_raw = await broker.fetch_candles(
            config.trade_pair, "H4", count=20,
        )
        h4 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h4_raw
        ]

        # Current price from latest H4 candle
        current_price = h4[-1].close if h4 else None
        insight["current_price"] = round(current_price, 5) if current_price else None

        # Zone proximity analysis
        if current_price and zones:
            nearest = min(zones, key=lambda z: abs(z.price_level - current_price))
            dist_pips = abs(nearest.price_level - current_price) / 0.0001
            insight["nearest_zone"] = {
                "price": round(nearest.price_level, 5),
                "type": nearest.zone_type,
                "distance_pips": round(dist_pips, 1),
                "touches": nearest.strength,
            }
            insight["checks"]["zone_proximity"] = dist_pips < 30  # within 30 pips

        # Rejection wick analysis on latest H4 candle
        if h4:
            candle = h4[-1]
            has_buy_wick = _is_rejection_wick_buy(candle)
            has_sell_wick = _is_rejection_wick_sell(candle)
            touched_zones = [z for z in zones if _candle_touches_zone(candle, z)]
            insight["latest_h4"] = {
                "time": candle.time,
                "open": round(candle.open, 5),
                "high": round(candle.high, 5),
                "low": round(candle.low, 5),
                "close": round(candle.close, 5),
                "buy_rejection_wick": has_buy_wick,
                "sell_rejection_wick": has_sell_wick,
                "zones_touched": len(touched_zones),
            }
            insight["checks"]["rejection_wick"] = (
                (has_buy_wick and any(z.zone_type == "support" for z in touched_zones))
                or (has_sell_wick and any(z.zone_type == "resistance" for z in touched_zones))
            )
        else:
            insight["checks"]["rejection_wick"] = False

        signal = evaluate_signal(h4, zones)
        if signal is None:
            insight["checks"]["risk_calculated"] = False
            insight["result"] = "no_signal"
            self.last_insight = insight
            return None

        # 3 ── Risk calculations
        atr = calculate_atr(daily)
        sl = calculate_sl(
            signal.entry_price,
            signal.direction,
            signal.sr_zone.price_level,
            atr,
        )
        tp = calculate_tp(signal.entry_price, signal.direction, sl, zones)

        insight["checks"]["risk_calculated"] = True
        insight["signal"] = {
            "direction": signal.direction,
            "entry": round(signal.entry_price, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "zone": round(signal.sr_zone.price_level, 5),
            "reason": signal.reason,
        }
        insight["atr"] = round(atr, 5)
        insight["result"] = "signal_found"
        self.last_insight = insight

        return StrategyResult(
            signal=signal,
            sl=sl,
            tp=tp,
            atr=atr,
        )
