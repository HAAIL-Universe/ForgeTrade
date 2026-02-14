"""Tests for Phase 5 — Backtest Engine.

Covers the backtest engine, stats calculation, Sharpe ratio,
and backtest persistence.
"""

import math

import pytest

from app.backtest.engine import BacktestEngine
from app.backtest.stats import calculate_stats, _sharpe, _max_drawdown
from app.repos.backtest_repo import BacktestRepo
from app.repos.db import init_db
from app.strategy.models import CandleData


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_candle(time, o, h, l, c, vol=1000):
    return CandleData(time=time, open=o, high=h, low=l, close=c, volume=vol)


def _daily_fixture():
    """50 daily candles oscillating between ~1.0800 and ~1.1000."""
    base_prices = [
        1.0950, 1.0930, 1.0900, 1.0870, 1.0840, 1.0810, 1.0800,
        1.0820, 1.0850, 1.0880, 1.0910, 1.0940, 1.0970, 1.1000,
        1.0980, 1.0960, 1.0930, 1.0900, 1.0870, 1.0840, 1.0802,
        1.0825, 1.0855, 1.0885, 1.0915, 1.0945, 1.0975, 1.0998,
        1.0975, 1.0950, 1.0920, 1.0890, 1.0860, 1.0830, 1.0805,
        1.0830, 1.0860, 1.0890, 1.0920, 1.0950, 1.0980, 1.0995,
        1.0970, 1.0940, 1.0910, 1.0880, 1.0850, 1.0820, 1.0808,
        1.0830,
    ]
    spread = 0.0020
    return [
        _make_candle(f"2025-01-{i+1:02d}T00:00:00Z", b, b + spread, b - spread, b)
        for i, b in enumerate(base_prices)
    ]


def _h4_fixture_one_winning_trade():
    """4H candles producing exactly one buy trade that hits TP.

    Sequence:
    - Several candles trending down toward support ~1.0800
    - Signal candle: touches support with bullish rejection wick → buy
    - Follow-up candles: price rises and hits TP near resistance ~1.1000
    """
    candles = [
        _make_candle("2025-02-01T00:00:00Z", 1.0900, 1.0910, 1.0890, 1.0895),
        _make_candle("2025-02-01T04:00:00Z", 1.0895, 1.0905, 1.0885, 1.0890),
        _make_candle("2025-02-01T08:00:00Z", 1.0890, 1.0900, 1.0880, 1.0885),
        _make_candle("2025-02-01T12:00:00Z", 1.0885, 1.0895, 1.0870, 1.0875),
        _make_candle("2025-02-01T16:00:00Z", 1.0875, 1.0885, 1.0860, 1.0865),
        _make_candle("2025-02-01T20:00:00Z", 1.0865, 1.0875, 1.0845, 1.0850),
        _make_candle("2025-02-02T00:00:00Z", 1.0850, 1.0860, 1.0835, 1.0840),
        # Signal candle: rejection wick at support
        _make_candle("2025-02-02T04:00:00Z", 1.0820, 1.0835, 1.0795, 1.0830),
        # Recovery candles — price rising
        _make_candle("2025-02-02T08:00:00Z", 1.0830, 1.0880, 1.0825, 1.0870),
        _make_candle("2025-02-02T12:00:00Z", 1.0870, 1.0930, 1.0860, 1.0920),
        _make_candle("2025-02-02T16:00:00Z", 1.0920, 1.0970, 1.0910, 1.0960),
        # TP-hit candle — high reaches resistance zone
        _make_candle("2025-02-02T20:00:00Z", 1.0960, 1.1010, 1.0950, 1.0990),
    ]
    return candles


def _make_config():
    from app.config import Config
    return Config(
        oanda_account_id="test",
        oanda_api_token="test",
        oanda_environment="practice",
        trade_pair="EUR_USD",
        risk_per_trade_pct=1.0,
        max_drawdown_pct=10.0,
        session_start_utc=7,
        session_end_utc=21,
        db_path=":memory:",
        log_level="WARNING",
        health_port=8080,
    )


# ── Backtest engine ─────────────────────────────────────────────────────


class TestBacktestEngine:

    def test_backtest_known_data(self):
        """Known candle fixture produces expected trade count."""
        engine = BacktestEngine(_make_config())
        result = engine.run(
            daily_candles=_daily_fixture(),
            h4_candles=_h4_fixture_one_winning_trade(),
            initial_equity=10_000.0,
        )
        trades = result["trades"]
        # Fixture is designed to produce exactly 1 winning buy trade
        assert len(trades) >= 1
        winning = [t for t in trades if t["pnl"] > 0]
        assert len(winning) >= 1
        assert result["final_equity"] > 10_000.0

    def test_backtest_empty_candles(self):
        """Empty 4H candles produce no trades."""
        engine = BacktestEngine(_make_config())
        result = engine.run(
            daily_candles=_daily_fixture(),
            h4_candles=[],
            initial_equity=10_000.0,
        )
        assert result["trades"] == []
        assert result["final_equity"] == 10_000.0


# ── Stats calculation ────────────────────────────────────────────────────


class TestStatsCalculation:

    def test_stats_calculation(self):
        """Win rate, profit factor correct for known trade set."""
        trades = [
            {"pnl": 200.0},
            {"pnl": -100.0},
            {"pnl": 150.0},
            {"pnl": -50.0},
        ]
        stats = calculate_stats(trades)
        assert stats["total_trades"] == 4
        assert stats["winning_trades"] == 2
        assert stats["losing_trades"] == 2
        # win_rate = 2/4 = 0.5
        assert stats["win_rate"] == 0.5
        # profit_factor = (200+150) / (100+50) = 350/150 = 2.3333
        assert abs(stats["profit_factor"] - 2.3333) < 0.01
        # net_pnl = 200 - 100 + 150 - 50 = 200
        assert stats["net_pnl"] == 200.0

    def test_stats_empty(self):
        """Empty trade list returns zero stats."""
        stats = calculate_stats([])
        assert stats["total_trades"] == 0
        assert stats["net_pnl"] == 0.0

    def test_sharpe_ratio(self):
        """Sharpe correct for a known returns series."""
        pnls = [100.0, -50.0, 80.0, -30.0, 120.0]
        mean_val = sum(pnls) / len(pnls)  # 44.0
        var = sum((p - mean_val) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var)
        expected_sharpe = (mean_val / std) * math.sqrt(252)

        computed = _sharpe(pnls)
        assert abs(computed - expected_sharpe) < 0.001

    def test_max_drawdown(self):
        """Max drawdown computed from cumulative P&L."""
        pnls = [100.0, 50.0, -200.0, 30.0]
        # cumulative: 100, 150, -50, -20
        # peak:       100, 150, 150, 150
        # dd:           0,   0, 200, 170
        # max_dd = 200
        assert _max_drawdown(pnls) == 200.0


# ── Backtest repo ────────────────────────────────────────────────────────


class TestBacktestRepo:

    def test_backtest_persisted(self, tmp_path):
        """Backtest run row exists in DB after insert."""
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        repo = BacktestRepo(db_path)

        stats = {
            "total_trades": 10,
            "winning_trades": 6,
            "losing_trades": 4,
            "win_rate": 0.6,
            "profit_factor": 2.0,
            "sharpe_ratio": 1.5,
            "max_drawdown": 500.0,
            "net_pnl": 1200.0,
        }
        row_id = repo.insert_run(
            pair="EUR_USD",
            start_date="2024-01-01",
            end_date="2025-01-01",
            stats=stats,
        )
        assert row_id >= 1

        runs = repo.get_runs()
        assert len(runs) == 1
        assert runs[0]["total_trades"] == 10
        assert runs[0]["win_rate"] == 0.6
        assert runs[0]["net_pnl"] == 1200.0
