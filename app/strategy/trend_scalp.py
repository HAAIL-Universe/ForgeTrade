"""Trend-Confirmed Micro-Scalp strategy for XAU_USD.

Implements ``StrategyProtocol``.  Uses H1 trend detection, M1 pullback
logic, S5 precision timing, and scalp-specific SL/TP calculations.
"""

from typing import Optional

from app.risk.scalp_sl_tp import calculate_scalp_sl, calculate_scalp_tp
from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.models import CandleData, EntrySignal, INSTRUMENT_PIP_VALUES, SRZone
from app.strategy.scalp_signals import ScalpEntrySignal, evaluate_scalp_entry
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

    MAX_SPREAD_PIPS: float = 8.0
    DEFAULT_RR_RATIO: float = 1.5

    def __init__(self) -> None:
        self.last_insight: dict = {}

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

        # Base insight — updated progressively through the evaluation
        checks = {
            "trend_detected": False,
            "pullback_to_ema": False,
            "spread_acceptable": False,
            "confirmation_pattern": False,
            "sl_valid": False,
            "risk_calculated": False,
        }
        self.last_insight = {
            "strategy": "Trend-Confirmed Scalp",
            "pair": instrument,
            "checks": checks,
        }

        # 1 ── M5 trend detection (scalp-speed, fast EMAs)
        m5_raw = await broker.fetch_candles(instrument, "M5", count=30)
        m5_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in m5_raw
        ]
        trend = detect_trend(m5_candles, ema_fast=9, ema_slow=21)

        # Fallback: if M5 is flat, check M15 with standard EMAs
        if trend.direction == "flat":
            m15_raw = await broker.fetch_candles(instrument, "M15", count=50)
            m15_candles = [
                CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
                for c in m15_raw
            ]
            trend = detect_trend(m15_candles, ema_fast=9, ema_slow=21)

        # Second fallback: if still flat, use EMA slope direction on M5
        # (EMAs aligned but price between them — still a usable bias)
        if trend.direction == "flat" and len(m5_candles) >= 21:
            from app.strategy.indicators import calculate_ema as _ema_calc
            fast_v = _ema_calc(m5_candles, 9)
            slow_v = _ema_calc(m5_candles, 21)
            if fast_v and slow_v:
                slope = fast_v[-1] - slow_v[-1]
                # If slope is meaningful (> 0.5 for gold ≈ $0.50 separation)
                if abs(slope) > 0.5:
                    from app.strategy.trend import TrendState
                    trend = TrendState(
                        direction="bullish" if slope > 0 else "bearish",
                        ema_fast_value=fast_v[-1],
                        ema_slow_value=slow_v[-1],
                        slope=slope,
                    )

        self.last_insight["trend"] = {
            "direction": trend.direction,
            "ema_fast": round(trend.ema_fast_value, 2),
            "ema_slow": round(trend.ema_slow_value, 2),
            "slope": round(trend.slope, 4),
        }

        # 1b ── Multi-timeframe trend snapshot for dashboard cycling
        multi_tf_trends = {}
        for tf_gran, tf_label in [("S5", "S5"), ("M1", "M1"), ("M5", "M5"),
                                   ("M15", "M15"), ("M30", "M30"), ("H1", "H1")]:
            try:
                if tf_gran == "H1":
                    # Re-use already fetched H1 trend
                    multi_tf_trends[tf_label] = {
                        "direction": trend.direction,
                        "slope": round(trend.slope, 4),
                    }
                else:
                    tf_raw = await broker.fetch_candles(instrument, tf_gran, count=50)
                    tf_candles = [
                        CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
                        for c in tf_raw
                    ]
                    tf_trend = detect_trend(tf_candles)
                    multi_tf_trends[tf_label] = {
                        "direction": tf_trend.direction,
                        "slope": round(tf_trend.slope, 4),
                    }
            except Exception:
                multi_tf_trends[tf_label] = {"direction": "unknown", "slope": 0}
        self.last_insight["multi_tf_trends"] = multi_tf_trends

        if trend.direction == "flat":
            self.last_insight["result"] = "no_trend"
            return None
        checks["trend_detected"] = True

        # 2 ── M1 pullback and confirmation
        m1_raw = await broker.fetch_candles(instrument, "M1", count=20)
        m1_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in m1_raw
        ]

        # 3 ── S5 precision timing + spread check
        s5_raw = await broker.fetch_candles(instrument, "S5", count=20)
        s5_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in s5_raw
        ]

        # Current price snapshot for the dashboard
        if m1_candles:
            last_m1 = m1_candles[-1]
            self.last_insight["latest_candle"] = {
                "timeframe": "M1",
                "time": last_m1.time,
                "open": last_m1.open,
                "high": last_m1.high,
                "low": last_m1.low,
                "close": last_m1.close,
            }

        # Spread check — use the *tightest* S5 candle as spread proxy
        # (the widest candles reflect price action, not spread)
        if s5_candles:
            min_range = min(c.high - c.low for c in s5_candles)
            spread_pips = min_range / pip_value
            self.last_insight["spread_pips"] = round(spread_pips, 1)
            self.last_insight["max_spread_pips"] = self.MAX_SPREAD_PIPS
            if spread_pips > self.MAX_SPREAD_PIPS:
                self.last_insight["result"] = "spread_too_wide"
                return None
        checks["spread_acceptable"] = True

        # 4 ── Evaluate scalp entry
        entry_signal = evaluate_scalp_entry(m1_candles, s5_candles, trend)
        if entry_signal is None:
            # Determine which sub-check failed for insight
            from app.strategy.indicators import calculate_ema as _ema
            ema_vals = _ema(m1_candles, 9)
            if ema_vals and m1_candles:
                ema_cur = ema_vals[-1]
                price = m1_candles[-1].close
                self.last_insight["ema9"] = round(ema_cur, 2)
                self.last_insight["price_vs_ema"] = round(price - ema_cur, 2)
                # Check if it was pullback or confirmation that failed
                if trend.direction == "bullish" and price <= ema_cur * 1.006:
                    checks["pullback_to_ema"] = True
                    self.last_insight["result"] = "no_confirmation_pattern"
                elif trend.direction == "bearish" and price >= ema_cur * 0.994:
                    checks["pullback_to_ema"] = True
                    self.last_insight["result"] = "no_confirmation_pattern"
                else:
                    self.last_insight["result"] = "no_pullback"
            else:
                self.last_insight["result"] = "no_pullback"
            return None

        checks["pullback_to_ema"] = True
        checks["confirmation_pattern"] = True
        self.last_insight["signal"] = {
            "direction": entry_signal.direction,
            "entry_price": entry_signal.entry_price,
            "reason": entry_signal.reason,
        }

        # 5 ── Calculate SL and TP
        sl = calculate_scalp_sl(
            entry_price=entry_signal.entry_price,
            direction=entry_signal.direction,
            candles_m1=m1_candles,
            pip_value=pip_value,
        )
        if sl is None:
            self.last_insight["result"] = "sl_out_of_bounds"
            return None
        checks["sl_valid"] = True

        tp = calculate_scalp_tp(
            entry_price=entry_signal.entry_price,
            direction=entry_signal.direction,
            sl_price=sl,
            rr_ratio=self.DEFAULT_RR_RATIO,
        )
        checks["risk_calculated"] = True
        self.last_insight["sl"] = sl
        self.last_insight["tp"] = tp
        self.last_insight["rr_ratio"] = self.DEFAULT_RR_RATIO
        self.last_insight["result"] = "signal_found"

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
