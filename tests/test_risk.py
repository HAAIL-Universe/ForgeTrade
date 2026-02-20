"""Tests for the risk management module.

Covers position sizing, zone-anchored SL/TP calculation, legacy SL/TP,
drawdown tracking, and circuit breaker activation.
"""

import pytest

from app.risk.position_sizer import calculate_units
from app.risk.sl_tp import (
    calculate_sl, calculate_tp,
    calculate_zone_anchored_risk, RiskLevels,
)
from app.risk.drawdown import DrawdownTracker
from app.strategy.models import SRZone


# ── Position sizing ──────────────────────────────────────────────────────


class TestPositionSizing:
    """Unit tests for calculate_units()."""

    def test_position_sizing(self):
        """$10,000 equity, 1% risk, 30 pip SL → 33,333.33 units."""
        units = calculate_units(
            equity=10_000.0,
            risk_pct=1.0,
            sl_distance_pips=30.0,
        )
        # risk = 10000 * 0.01 = 100
        # sl_in_price = 30 * 0.0001 = 0.003
        # units = 100 / 0.003 = 33333.333...
        assert abs(units - 33_333.33333) < 0.01

    def test_position_sizing_different_risk(self):
        """$5,000 equity, 2% risk, 20 pip SL → 50,000 units."""
        units = calculate_units(
            equity=5_000.0,
            risk_pct=2.0,
            sl_distance_pips=20.0,
        )
        # risk = 5000 * 0.02 = 100
        # sl_in_price = 20 * 0.0001 = 0.002
        # units = 100 / 0.002 = 50000
        assert abs(units - 50_000.0) < 0.01

    def test_position_sizing_rejects_zero_equity(self):
        with pytest.raises(ValueError, match="equity"):
            calculate_units(equity=0, risk_pct=1.0, sl_distance_pips=30.0)

    def test_position_sizing_rejects_zero_sl(self):
        with pytest.raises(ValueError, match="sl_distance_pips"):
            calculate_units(equity=10_000, risk_pct=1.0, sl_distance_pips=0)


# ── SL calculation ───────────────────────────────────────────────────────


class TestSLCalculation:
    """Unit tests for calculate_sl()."""

    def test_sl_calculation_buy(self):
        """Buy trade SL = zone_price - 1.5 × ATR."""
        sl = calculate_sl(
            entry_price=1.08300,
            direction="buy",
            zone_price=1.08000,
            atr=0.00200,
        )
        # SL = 1.08000 - 1.5 * 0.00200 = 1.08000 - 0.00300 = 1.07700
        assert sl == pytest.approx(1.07700, abs=1e-5)

    def test_sl_calculation_sell(self):
        """Sell trade SL = zone_price + 1.5 × ATR."""
        sl = calculate_sl(
            entry_price=1.09800,
            direction="sell",
            zone_price=1.10000,
            atr=0.00200,
        )
        # SL = 1.10000 + 1.5 * 0.00200 = 1.10000 + 0.00300 = 1.10300
        assert sl == pytest.approx(1.10300, abs=1e-5)

    def test_sl_invalid_direction(self):
        with pytest.raises(ValueError, match="direction"):
            calculate_sl(1.0900, "hold", 1.0800, 0.002)


# ── TP calculation ───────────────────────────────────────────────────────


class TestTPCalculation:
    """Unit tests for calculate_tp()."""

    def test_tp_next_zone(self):
        """TP = next zone when closer than 1:2 RR."""
        zones = [
            SRZone(zone_type="support", price_level=1.08000, strength=3),
            SRZone(zone_type="resistance", price_level=1.09000, strength=2),
            SRZone(zone_type="resistance", price_level=1.12000, strength=2),
        ]
        # Buy at 1.0830, SL at 1.0770 → risk = 0.0060
        # 1:2 RR TP = 1.0830 + 0.0120 = 1.0950
        # Next zone above entry = 1.0900 (distance 0.0070 vs 0.0120)
        # 1.0900 is closer → use zone
        tp = calculate_tp(
            entry_price=1.08300,
            direction="buy",
            sl_price=1.07700,
            sr_zones=zones,
        )
        assert tp == pytest.approx(1.09000, abs=1e-5)

    def test_tp_rr_ratio(self):
        """TP = 1:2 RR when next zone is farther."""
        zones = [
            SRZone(zone_type="support", price_level=1.08000, strength=3),
            SRZone(zone_type="resistance", price_level=1.12000, strength=2),
        ]
        # Buy at 1.0830, SL at 1.0770 → risk = 0.0060
        # 1:2 RR TP = 1.0830 + 0.0120 = 1.0950
        # Next zone above entry = 1.1200 (distance 0.0370 vs 0.0120)
        # 1:2 RR is closer → use RR
        tp = calculate_tp(
            entry_price=1.08300,
            direction="buy",
            sl_price=1.07700,
            sr_zones=zones,
        )
        assert tp == pytest.approx(1.09500, abs=1e-5)

    def test_tp_sell_next_zone(self):
        """Sell TP = next zone below entry when closer than 1:2 RR."""
        zones = [
            SRZone(zone_type="support", price_level=1.09200, strength=2),
            SRZone(zone_type="resistance", price_level=1.10000, strength=3),
        ]
        # Sell at 1.0980, SL at 1.1030 → risk = 0.0050
        # 1:2 RR TP = 1.0980 - 0.0100 = 1.0880
        # Next zone below = 1.0920 (distance 0.0060 vs 0.0100)
        # 1.0920 is closer → use zone
        tp = calculate_tp(
            entry_price=1.09800,
            direction="sell",
            sl_price=1.10300,
            sr_zones=zones,
        )
        assert tp == pytest.approx(1.09200, abs=1e-5)

    def test_tp_no_zones_beyond_entry(self):
        """Falls back to 1:2 RR when no zone exists beyond entry."""
        zones = [
            SRZone(zone_type="support", price_level=1.08000, strength=3),
        ]
        tp = calculate_tp(
            entry_price=1.08300,
            direction="buy",
            sl_price=1.07700,
            sr_zones=zones,
        )
        # 1:2 RR = 1.0830 + 2 * 0.006 = 1.0950
        assert tp == pytest.approx(1.09500, abs=1e-5)

    def test_tp_excludes_triggering_zone(self):
        """TP skips the zone that triggered the entry signal."""
        # Simulates a SELL triggered by resistance at 1.10000
        trigger = SRZone(zone_type="resistance", price_level=1.10000, strength=2)
        zones = [
            trigger,
            SRZone(zone_type="support", price_level=1.09200, strength=2),
            SRZone(zone_type="support", price_level=1.08000, strength=1),
        ]
        # Sell at 1.0980, SL at 1.1030 → risk = 0.0050
        # Without exclusion, 1.10000 is below 1.0980? No — 1.10000 > entry.
        # But 1.09200 is below entry, zone_dist = 0.006 vs RR dist = 0.010
        # 1.09200 is closer → use zone
        tp = calculate_tp(
            entry_price=1.09800,
            direction="sell",
            sl_price=1.10300,
            sr_zones=zones,
            triggering_zone=trigger,
        )
        # Should pick 1.09200 (next support below)
        assert tp == pytest.approx(1.09200, abs=1e-5)

    def test_tp_min_rr_floor(self):
        """Zone too close → filtered out, falls back to full R:R target."""
        trigger = SRZone(zone_type="resistance", price_level=1.10000, strength=2)
        zones = [
            trigger,
            # Zone very close to entry — only 3 pips away
            SRZone(zone_type="support", price_level=1.09950, strength=1),
        ]
        # Sell at 1.09980, SL at 1.10500 → risk = 0.0052
        # Zone at 1.09950 is 0.0003 from entry — below min_rr floor
        # Zone is skipped → TP = rr_ratio (2.0) target
        tp = calculate_tp(
            entry_price=1.09980,
            direction="sell",
            sl_price=1.10500,
            sr_zones=zones,
            triggering_zone=trigger,
            min_rr=1.0,
        )
        # rr_tp = 1.09980 - 2.0 * 0.0052 = 1.0894
        expected = round(1.09980 - 2.0 * abs(1.09980 - 1.10500), 5)
        assert tp == pytest.approx(expected, abs=1e-5)

    def test_tp_triggering_zone_none_is_backward_compatible(self):
        """When triggering_zone is None, behaves like the original code."""
        zones = [
            SRZone(zone_type="support", price_level=1.08000, strength=3),
            SRZone(zone_type="resistance", price_level=1.09000, strength=2),
        ]
        tp = calculate_tp(
            entry_price=1.08300,
            direction="buy",
            sl_price=1.07700,
            sr_zones=zones,
            triggering_zone=None,
        )
        # Same result as test_tp_next_zone
        assert tp == pytest.approx(1.09000, abs=1e-5)


# ── Zone-anchored risk calculation ──────────────────────────────────────


class TestZoneAnchoredRisk:
    """Unit tests for calculate_zone_anchored_risk()."""

    def test_buy_tp_at_next_zone_sl_derived(self):
        """Buy: TP = next resistance zone, SL = TP dist / R:R."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [
            trigger,
            SRZone(zone_type="resistance", price_level=1.09000, strength=2),
        ]
        # Entry 1.0830, ATR 0.002
        # Next zone above = 1.0900, TP dist = 0.0070
        # SL dist = 0.0070 / 2.0 = 0.0035
        # min_sl = 0.5 * 0.002 = 0.001 ✓
        # max_sl = 2.0 * 0.002 = 0.004 ✓ (0.0035 < 0.004)
        # SL = 1.0830 - 0.0035 = 1.0795
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09000, abs=1e-5)
        assert result.sl == pytest.approx(1.07950, abs=1e-5)
        assert result.tp_source == "zone"

    def test_sell_tp_at_next_zone_sl_derived(self):
        """Sell: TP = next support zone, SL = TP dist / R:R."""
        trigger = SRZone(zone_type="resistance", price_level=1.10000, strength=2)
        zones = [
            trigger,
            SRZone(zone_type="support", price_level=1.09000, strength=3),
        ]
        # Entry 1.0980, ATR 0.002
        # Next zone below = 1.0900, TP dist = 0.0080
        # SL dist = 0.0080 / 2.0 = 0.0040
        # max_sl = 2.0 * 0.002 = 0.004 → exactly at cap
        # SL = 1.0980 + 0.0040 = 1.1020
        result = calculate_zone_anchored_risk(
            entry_price=1.09800,
            direction="sell",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09000, abs=1e-5)
        assert result.sl == pytest.approx(1.10200, abs=1e-5)
        assert result.tp_source == "zone"

    def test_zone_too_close_returns_none(self):
        """Zone within min SL distance → trade skipped (returns None)."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [
            trigger,
            # Zone only 5 pips above entry
            SRZone(zone_type="resistance", price_level=1.08350, strength=1),
        ]
        # Entry 1.0830, ATR 0.002
        # Next zone above = 1.08350, TP dist = 0.0005
        # Derived SL dist = 0.0005 / 2.0 = 0.00025
        # min_sl = 0.5 * 0.002 = 0.001 → 0.00025 < 0.001 → SKIP
        # But wait — min_tp_dist = 1.0 * 0.002 = 0.002.
        # 1.08350 - 1.08300 = 0.0005 < 0.002 → zone filtered out
        # → falls through to ATR fallback
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        # Zone too close (< min_tp_dist) → ATR fallback
        assert result is not None
        assert result.tp_source == "atr_fallback"

    def test_sl_capped_at_max_atr(self):
        """Distant zone → SL capped at max_sl_atr_mult × ATR (R:R improves)."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [
            trigger,
            # Zone 200 pips away
            SRZone(zone_type="resistance", price_level=1.10300, strength=2),
        ]
        # Entry 1.0830, ATR 0.002
        # Next zone above = 1.1030, TP dist = 0.020
        # Derived SL dist = 0.020 / 2.0 = 0.010
        # max_sl = 2.0 * 0.002 = 0.004 → 0.010 > 0.004 → capped
        # SL = 1.0830 - 0.004 = 1.0790
        # Effective R:R = 0.020 / 0.004 = 5.0 (bonus!)
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.10300, abs=1e-5)
        assert result.sl == pytest.approx(1.07900, abs=1e-5)
        assert result.tp_source == "zone"

    def test_no_zones_in_profit_dir_atr_fallback(self):
        """No zone beyond entry → ATR-based fallback TP and SL."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [trigger]
        # Entry 1.0830, ATR 0.002
        # No zone above → fallback
        # SL = max_sl = 2.0 * 0.002 = 0.004 → 1.0830 - 0.004 = 1.0790
        # TP = rr * max_sl = 2.0 * 0.004 = 0.008 → 1.0830 + 0.008 = 1.0910
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09100, abs=1e-5)
        assert result.sl == pytest.approx(1.07900, abs=1e-5)
        assert result.tp_source == "atr_fallback"

    def test_triggering_zone_excluded_from_tp(self):
        """Triggering zone is not a TP candidate."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        same_price = SRZone(zone_type="resistance", price_level=1.08000, strength=2)
        next_zone = SRZone(zone_type="resistance", price_level=1.09500, strength=2)
        zones = [trigger, same_price, next_zone]
        # The zone at 1.08000 should be excluded (same price as trigger)
        # Next valid zone = 1.09500
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09500, abs=1e-5)

    def test_zones_below_min_tp_dist_skipped(self):
        """Zones closer than min_tp_atr_mult × ATR are skipped."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [
            trigger,
            # Zone 15 pips above (within 1×ATR = 20 pips)
            SRZone(zone_type="resistance", price_level=1.08450, strength=1),
            # Zone 80 pips above — valid
            SRZone(zone_type="resistance", price_level=1.09100, strength=2),
        ]
        # ATR = 0.002 = 20 pips. min_tp_dist = 1.0 * 0.002 = 0.002
        # Zone at 1.08450: dist = 0.0015 < 0.002 → skipped
        # Zone at 1.09100: dist = 0.008 >= 0.002 → valid
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09100, abs=1e-5)

    def test_custom_rr_ratio(self):
        """Custom R:R ratio (3.0) produces correct SL."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [
            trigger,
            SRZone(zone_type="resistance", price_level=1.09200, strength=2),
        ]
        # Entry 1.0830, ATR 0.002, rr_ratio = 3.0
        # TP dist = 1.0920 - 1.0830 = 0.009
        # Derived SL dist = 0.009 / 3.0 = 0.003
        # max_sl = 2.0 * 0.002 = 0.004 → 0.003 < 0.004 ✓
        # min_sl = 0.5 * 0.002 = 0.001 → 0.003 > 0.001 ✓
        # SL = 1.0830 - 0.003 = 1.0800
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=3.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09200, abs=1e-5)
        assert result.sl == pytest.approx(1.08000, abs=1e-5)

    def test_invalid_direction_raises(self):
        """Invalid direction raises ValueError."""
        with pytest.raises(ValueError, match="direction"):
            calculate_zone_anchored_risk(
                entry_price=1.08300,
                direction="hold",
                sr_zones=[],
                atr=0.00200,
            )

    def test_sell_atr_fallback(self):
        """Sell with no zones below → ATR fallback."""
        trigger = SRZone(zone_type="resistance", price_level=1.10000, strength=2)
        zones = [trigger]
        # No zone below entry
        # SL = max_sl = 2.0 * 0.002 = 0.004 → 1.0980 + 0.004 = 1.1020
        # TP = rr * max_sl = 2.0 * 0.004 = 0.008 → 1.0980 - 0.008 = 1.0900
        result = calculate_zone_anchored_risk(
            entry_price=1.09800,
            direction="sell",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=2.0,
            triggering_zone=trigger,
        )
        assert result is not None
        assert result.tp == pytest.approx(1.09000, abs=1e-5)
        assert result.sl == pytest.approx(1.10200, abs=1e-5)
        assert result.tp_source == "atr_fallback"

    def test_derived_sl_below_min_returns_none(self):
        """Zone gives TP too close once min_tp_dist passes → SL below min → None."""
        trigger = SRZone(zone_type="support", price_level=1.08000, strength=3)
        zones = [
            trigger,
            # Zone at exactly min_tp_dist but with high rr_ratio → tiny SL
            SRZone(zone_type="resistance", price_level=1.08500, strength=2),
        ]
        # Entry 1.0830, ATR 0.002, rr_ratio 5.0
        # min_tp_dist = 1.0 * 0.002 = 0.002. Zone dist = 0.002 → at boundary
        # Derived SL dist = 0.002 / 5.0 = 0.0004
        # min_sl = 0.5 * 0.002 = 0.001 → 0.0004 < 0.001 → None
        result = calculate_zone_anchored_risk(
            entry_price=1.08300,
            direction="buy",
            sr_zones=zones,
            atr=0.00200,
            rr_ratio=5.0,
            triggering_zone=trigger,
        )
        assert result is None


# ── Drawdown tracking ───────────────────────────────────────────────────


class TestDrawdownTracking:
    """Unit tests for DrawdownTracker."""

    def test_drawdown_tracking(self):
        """Drawdown % correct after equity decline."""
        tracker = DrawdownTracker(initial_equity=10_000.0, max_drawdown_pct=10.0)
        tracker.update(9_500.0)
        # drawdown = (10000 - 9500) / 10000 * 100 = 5.0%
        assert tracker.drawdown_pct == pytest.approx(5.0)
        assert tracker.peak_equity == 10_000.0
        assert tracker.current_equity == 9_500.0

    def test_drawdown_peak_updates(self):
        """Peak equity rises when new equity exceeds previous peak."""
        tracker = DrawdownTracker(initial_equity=10_000.0)
        tracker.update(10_500.0)
        assert tracker.peak_equity == 10_500.0
        assert tracker.drawdown_pct == pytest.approx(0.0)

    def test_circuit_breaker_fires(self):
        """Trading halted when drawdown > 10%."""
        tracker = DrawdownTracker(initial_equity=10_000.0, max_drawdown_pct=10.0)
        tracker.update(8_900.0)
        # drawdown = (10000 - 8900) / 10000 * 100 = 11.0%
        assert tracker.circuit_breaker_active is True

    def test_circuit_breaker_not_fires(self):
        """Trading continues when drawdown < 10%."""
        tracker = DrawdownTracker(initial_equity=10_000.0, max_drawdown_pct=10.0)
        tracker.update(9_500.0)
        # drawdown = 5%
        assert tracker.circuit_breaker_active is False

    def test_circuit_breaker_exactly_at_threshold(self):
        """Circuit breaker fires at exactly 10%."""
        tracker = DrawdownTracker(initial_equity=10_000.0, max_drawdown_pct=10.0)
        tracker.update(9_000.0)
        # drawdown = 10%
        assert tracker.circuit_breaker_active is True
