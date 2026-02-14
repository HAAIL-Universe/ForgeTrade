"""Tests for the risk management module.

Covers position sizing, SL/TP calculation, drawdown tracking,
and circuit breaker activation.
"""

import pytest

from app.risk.position_sizer import calculate_units
from app.risk.sl_tp import calculate_sl, calculate_tp
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
