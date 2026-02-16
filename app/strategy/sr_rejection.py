"""S/R Rejection Wick strategy — extracted from the original engine.

Identifies support/resistance zones on Daily candles, then looks for
rejection wicks on H4 candles near those zones.
"""

import logging
from typing import Optional

from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData
from app.strategy.signals import evaluate_signal
from app.strategy.sr_zones import detect_sr_zones
from app.risk.sl_tp import calculate_sl, calculate_tp

logger = logging.getLogger("forgetrade")


class SRRejectionStrategy:
    """Detects S/R rejection-wick setups on D + H4 timeframes.

    Implements ``StrategyProtocol``.
    """

    async def evaluate(self, broker, config) -> Optional[StrategyResult]:
        """Fetch candles, detect zones, evaluate signal, compute SL/TP.

        Returns ``StrategyResult`` on a valid setup, ``None`` otherwise.
        """
        # 1 ── Fetch daily candles → detect S/R zones
        daily_raw = await broker.fetch_candles(
            config.trade_pair, "D", count=50,
        )
        daily = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in daily_raw
        ]
        zones = detect_sr_zones(daily)
        if not zones:
            logger.debug("SRRejection: no zones detected")
            return None

        # 2 ── Fetch 4H candles → evaluate signal
        h4_raw = await broker.fetch_candles(
            config.trade_pair, "H4", count=20,
        )
        h4 = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h4_raw
        ]
        signal = evaluate_signal(h4, zones)
        if signal is None:
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

        return StrategyResult(
            signal=signal,
            sl=sl,
            tp=tp,
            atr=atr,
        )
