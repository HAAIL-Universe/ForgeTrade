"""Momentum-Bias Micro-Scalp strategy for XAU_USD.

Implements ``StrategyProtocol``.  Uses M5 momentum bias detection,
M5 EMA(9) pullback logic, M1 precision timing, and scalp-specific
SL/TP calculations.
"""

from typing import Optional

from app.risk.scalp_sl_tp import calculate_scalp_sl, calculate_scalp_tp
from app.strategy.base import StrategyProtocol, StrategyResult
from app.strategy.indicators import calculate_atr
from app.strategy.models import CandleData, EntrySignal, INSTRUMENT_PIP_VALUES, SRZone
from app.strategy.scalp_signals import ScalpEntrySignal, evaluate_scalp_entry
from app.strategy.trend import detect_scalp_bias, detect_trend


class TrendScalpStrategy:
    """Momentum-bias scalp strategy for fast timeframes.

    Flow:
        1. Fetch 20× M5 candles → detect momentum bias + pullback check.
        2. If flat → return None.
        3. Fetch 20× M1 candles → check spread + confirmation pattern.
        4. Calculate scalp SL (M5 swing structure) and TP (fixed R:R).
        5. Return StrategyResult.
    """

    MAX_SPREAD_PIPS: float = 8.0
    DEFAULT_RR_RATIO: float = 3.0
    MIN_ATR_PIPS: float = 80.0  # $0.80 — skip entries when M5 ATR < this (consolidation)
    SESSION_END_BUFFER_MIN: int = 30  # No new entries within 30 min of session close

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
            "volatility_ok": False,
            "pullback_to_ema": False,
            "spread_acceptable": False,
            "confirmation_pattern": False,
            "sl_valid": False,
            "risk_calculated": False,
        }
        self.last_insight = {
            "strategy": "Momentum Scalp",
            "pair": instrument,
            "checks": checks,
        }

        # 1 ── M5 candles (used for BOTH bias detection AND SL swing structure)
        m5_raw = await broker.fetch_candles(instrument, "M5", count=20)
        m5_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in m5_raw
        ]

        # 1a ── Momentum bias (M5 gives structural significance)
        trend = detect_scalp_bias(
            m5_candles, lookback=15, pip_value=pip_value,
        )

        self.last_insight["trend"] = {
            "direction": trend.direction,
            "ema_fast": round(trend.ema_fast_value, 2),
            "ema_slow": round(trend.ema_slow_value, 2),
            "slope": round(trend.slope, 4),
        }
        self.last_insight["bias_method"] = "M5 momentum"

        # 1b ── Multi-timeframe trend snapshot for dashboard cycling
        multi_tf_trends = {}
        for tf_gran, tf_label in [("S5", "S5"), ("M1", "M1"), ("M5", "M5"),
                                   ("M15", "M15"), ("M30", "M30"), ("H1", "H1")]:
            try:
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
            self.last_insight["result"] = "no_bias"
            return None
        checks["trend_detected"] = True

        # 1c ── Volatility gate — skip consolidation / low-ATR periods
        m5_atr = calculate_atr(m5_candles, period=14)
        m5_atr_pips = m5_atr / pip_value if m5_atr > 0 else 0
        self.last_insight["m5_atr_pips"] = round(m5_atr_pips, 1)
        self.last_insight["min_atr_pips"] = self.MIN_ATR_PIPS
        if m5_atr_pips < self.MIN_ATR_PIPS:
            self.last_insight["result"] = "low_volatility"
            return None
        checks["volatility_ok"] = True

        # 2 ── M1 precision timing + spread check
        m1_raw = await broker.fetch_candles(instrument, "M1", count=20)
        m1_candles = [
            CandleData(c.time, c.open, c.high, c.low, c.close, c.volume)
            for c in m1_raw
        ]

        # Current price snapshot for the dashboard
        if m5_candles:
            last_m5 = m5_candles[-1]
            self.last_insight["latest_candle"] = {
                "timeframe": "M5",
                "time": last_m5.time,
                "open": last_m5.open,
                "high": last_m5.high,
                "low": last_m5.low,
                "close": last_m5.close,
            }

        # Spread check — use the *tightest* M1 candle as spread proxy
        if m1_candles:
            min_range = min(c.high - c.low for c in m1_candles)
            spread_pips = min_range / pip_value
            self.last_insight["spread_pips"] = round(spread_pips, 1)
            self.last_insight["max_spread_pips"] = self.MAX_SPREAD_PIPS
            if spread_pips > self.MAX_SPREAD_PIPS:
                self.last_insight["result"] = "spread_too_wide"
                return None
        checks["spread_acceptable"] = True

        # 3 ── Evaluate scalp entry (with-bias only)
        entry_signal = evaluate_scalp_entry(m5_candles, m1_candles, trend)
        if entry_signal is None:
            # Determine which sub-check failed for insight
            from app.strategy.indicators import calculate_ema as _ema
            ema_vals = _ema(m5_candles, 9)
            if ema_vals and m5_candles:
                ema_cur = ema_vals[-1]
                price = m5_candles[-1].close
                self.last_insight["ema9"] = round(ema_cur, 2)
                self.last_insight["price_vs_ema"] = round(price - ema_cur, 2)
                self.last_insight["result"] = "no_confirmation_pattern"
            else:
                self.last_insight["result"] = "no_data"
            return None

        checks["pullback_to_ema"] = True
        checks["confirmation_pattern"] = True
        self.last_insight["signal"] = {
            "direction": entry_signal.direction,
            "entry_price": entry_signal.entry_price,
            "reason": entry_signal.reason,
        }

        # 4 ── Calculate SL and TP
        sl = calculate_scalp_sl(
            entry_price=entry_signal.entry_price,
            direction=entry_signal.direction,
            candles_m1=m5_candles,
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
            rr_ratio=getattr(config, "rr_ratio", None) or self.DEFAULT_RR_RATIO,
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
            candle_time=m1_candles[-1].time if m1_candles else m5_candles[-1].time,
            reason=entry_signal.reason,
        )

        return StrategyResult(signal=signal, sl=sl, tp=tp, atr=None)
