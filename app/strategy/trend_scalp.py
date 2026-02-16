"""Trend-Confirmed Micro-Scalp strategy for XAU_USD.

Implements ``StrategyProtocol``.  Uses H1 trend detection, M1 pullback
logic, S5 precision timing, and scalp-specific SL/TP calculations.
"""

from typing import Optional

from app.risk.scalp_sl_tp import calculate_scalp_sl, calculate_scalp_tp
from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.models import CandleData, EntrySignal, INSTRUMENT_PIP_VALUES, SRZone
from app.strategy.scalp_signals import ScalpEntrySignal, evaluate_scalp_entry
from app.strategy.spread_filter import is_spread_acceptable
from app.strategy.trend import detect_trend


class TrendScalpStrategy:
    """Trend-confirmed scalp strategy for fast timeframes.

    Flow:
        1. Fetch 50× H1 candles → detect trend.
        2. If flat → return None.
        3. Fetch 20× M1 candles → check pullback to EMA(9).
        4. Fetch 5× S5 candles → check spread + confirmation pattern.
        5. Calculate scalp SL (swing structure) and TP (fixed R:R).
        6. Return StrategyResult.
    """

    MAX_SPREAD_PIPS: float = 4.0
    DEFAULT_RR_RATIO: float = 1.5

    async def evaluate(self, broker, config) -> Optional[StrategyResult]:
        """Run the trend-scalp evaluation pipeline.

        Args:
            broker: An ``OandaClient`` instance.
            config: The ``Config`` object (provides ``trade_pair``).

        Returns:
            ``StrategyResult`` if a scalp entry is found, else ``None``.
        """
        instrument = getattr(config, "trade_pair", "XAU_USD")
        pip_value = INSTRUMENT_PIP_VALUES.get(instrument, 0.01)

        # 1 ── H1 trend detection
        h1_raw = await broker.fetch_candles(instrument, "H1", count=50)
        h1_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in h1_raw
        ]
        trend = detect_trend(h1_candles)
        if trend.direction == "flat":
            return None

        # 2 ── M1 pullback and confirmation
        m1_raw = await broker.fetch_candles(instrument, "M1", count=20)
        m1_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in m1_raw
        ]

        # 3 ── S5 precision timing + spread check
        s5_raw = await broker.fetch_candles(instrument, "S5", count=5)
        s5_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in s5_raw
        ]

        # Spread check using S5 candle as proxy
        if s5_candles:
            last_s5 = s5_candles[-1]
            # Estimate bid/ask from the S5 candle
            mid = last_s5.close
            half_spread = (last_s5.high - last_s5.low) / 2
            bid_est = mid - half_spread
            ask_est = mid + half_spread
            if not is_spread_acceptable(bid_est, ask_est, self.MAX_SPREAD_PIPS, pip_value):
                return None

        # 4 ── Evaluate scalp entry
        entry_signal = evaluate_scalp_entry(m1_candles, s5_candles, trend)
        if entry_signal is None:
            return None

        # 5 ── Calculate SL and TP
        sl = calculate_scalp_sl(
            entry_price=entry_signal.entry_price,
            direction=entry_signal.direction,
            candles_m1=m1_candles,
            pip_value=pip_value,
        )
        if sl is None:
            return None  # SL outside bounds

        tp = calculate_scalp_tp(
            entry_price=entry_signal.entry_price,
            direction=entry_signal.direction,
            sl_price=sl,
            rr_ratio=self.DEFAULT_RR_RATIO,
        )

        # Build an EntrySignal compatible with the existing engine
        # (uses a dummy SRZone since scalps don't use S/R zones)
        dummy_zone = SRZone(
            zone_type="trend_pullback",
            price_level=entry_signal.entry_price,
            strength=0,
        )
        signal = EntrySignal(
            direction=entry_signal.direction,
            entry_price=entry_signal.entry_price,
            sr_zone=dummy_zone,
            candle_time=m1_candles[-1].time,
            reason=entry_signal.reason,
        )

        return StrategyResult(signal=signal, sl=sl, tp=tp, atr=None)
