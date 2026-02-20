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
from app.strategy.trend import detect_trend
from app.risk.sl_tp import calculate_zone_anchored_risk

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
            config.trade_pair, "H4", count=60,
        )
        h4 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h4_raw
        ]

        # Current price from latest H4 candle
        current_price = h4[-1].close if h4 else None
        insight["current_price"] = round(current_price, 5) if current_price else None

        # H4 trend context (EMA 21/50) — informational, used as guide
        trend = detect_trend(h4)
        insight["trend"] = {
            "direction": trend.direction,
            "ema_fast": round(trend.ema_fast_value, 5) if trend.ema_fast_value else 0,
            "ema_slow": round(trend.ema_slow_value, 5) if trend.ema_slow_value else 0,
        }
        insight["checks"]["trend_detected"] = trend.direction != "flat"

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

            # Dynamic role: where is price relative to each touched zone?
            acting_roles = []
            for z in touched_zones:
                role = "support" if candle.close >= z.price_level else "resistance"
                acting_roles.append({
                    "zone": round(z.price_level, 5),
                    "original": z.zone_type,
                    "acting_as": role,
                    "flipped": role != z.zone_type,
                })

            insight["latest_h4"] = {
                "time": candle.time,
                "open": round(candle.open, 5),
                "high": round(candle.high, 5),
                "low": round(candle.low, 5),
                "close": round(candle.close, 5),
                "buy_rejection_wick": has_buy_wick,
                "sell_rejection_wick": has_sell_wick,
                "zones_touched": len(touched_zones),
                "zone_roles": acting_roles,
            }
            insight["checks"]["rejection_wick"] = (
                (has_buy_wick and any(r["acting_as"] == "support" for r in acting_roles))
                or (has_sell_wick and any(r["acting_as"] == "resistance" for r in acting_roles))
            )

            # Determine potential signal direction for trend alignment check
            potential_dir = None
            for r in acting_roles:
                if r["acting_as"] == "support" and has_buy_wick:
                    potential_dir = "buy"
                    break
                if r["acting_as"] == "resistance" and has_sell_wick:
                    potential_dir = "sell"
                    break
            insight["potential_direction"] = potential_dir

            if potential_dir is None:
                insight["checks"]["trend_aligned"] = None  # no signal to judge
            elif potential_dir == "buy" and trend.direction == "bearish":
                insight["checks"]["trend_aligned"] = False
            elif potential_dir == "sell" and trend.direction == "bullish":
                insight["checks"]["trend_aligned"] = False
            else:
                insight["checks"]["trend_aligned"] = True
        else:
            insight["checks"]["rejection_wick"] = False
            insight["checks"]["trend_aligned"] = None

        signal = evaluate_signal(h4, zones, trend_direction=trend.direction)
        if signal is None:
            insight["checks"]["risk_calculated"] = False
            # Distinguish between no-signal and trend-blocked
            insight["result"] = "trend_blocked" if insight["checks"].get("trend_aligned") is False else "no_signal"
            self.last_insight = insight
            return None

        # 3 ── Risk calculations (zone-anchored: TP first, SL derived)
        atr = calculate_atr(daily)
        rr = getattr(config, "rr_ratio", None) or 2.0
        risk_levels = calculate_zone_anchored_risk(
            entry_price=signal.entry_price,
            direction=signal.direction,
            sr_zones=zones,
            atr=atr,
            rr_ratio=rr,
            triggering_zone=signal.sr_zone,
        )

        if risk_levels is None:
            # Zone too close — SL would be below minimum
            insight["checks"]["risk_calculated"] = False
            insight["atr"] = round(atr, 5)
            insight["result"] = "zone_too_close"
            self.last_insight = insight
            return None

        sl = risk_levels.sl
        tp = risk_levels.tp

        insight["checks"]["risk_calculated"] = True
        insight["signal"] = {
            "direction": signal.direction,
            "entry": round(signal.entry_price, 5),
            "sl": round(sl, 5),
            "tp": round(tp, 5),
            "zone": round(signal.sr_zone.price_level, 5),
            "reason": signal.reason,
            "tp_source": risk_levels.tp_source,
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
