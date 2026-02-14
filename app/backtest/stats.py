"""Backtest statistics — pure functions for trade-series analysis."""

import math
from typing import Optional


def calculate_stats(trades: list[dict]) -> dict:
    """Compute summary statistics from a list of closed backtest trades.

    Each trade dict must have a ``"pnl"`` key (float).

    Returns:
        Dict matching the ``backtest_runs`` table columns:
        ``total_trades``, ``winning_trades``, ``losing_trades``,
        ``win_rate``, ``profit_factor``, ``sharpe_ratio``,
        ``max_drawdown``, ``net_pnl``.
    """
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": None,
            "sharpe_ratio": 0.0,
            "max_drawdown": 0.0,
            "net_pnl": 0.0,
        }

    pnls = [t["pnl"] for t in trades]
    total = len(pnls)
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p <= 0]

    winning = len(winners)
    losing = len(losers)
    win_rate = winning / total

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    profit_factor: Optional[float] = (
        gross_profit / gross_loss if gross_loss > 0 else None
    )

    net_pnl = sum(pnls)

    # Sharpe ratio (annualised, assuming ~252 trading days)
    sharpe_ratio = _sharpe(pnls)

    # Max drawdown from cumulative P&L curve
    max_drawdown = _max_drawdown(pnls)

    return {
        "total_trades": total,
        "winning_trades": winning,
        "losing_trades": losing,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "sharpe_ratio": round(sharpe_ratio, 4),
        "max_drawdown": round(max_drawdown, 4),
        "net_pnl": round(net_pnl, 2),
    }


# ── Helpers ──────────────────────────────────────────────────────────────


def _sharpe(pnls: list[float]) -> float:
    """Annualised Sharpe ratio from a P&L series.

    Uses sample standard deviation (n − 1).  Returns 0.0 when the series
    has fewer than 2 observations or zero variance.
    """
    n = len(pnls)
    if n < 2:
        return 0.0
    mean = sum(pnls) / n
    variance = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(252)


def _max_drawdown(pnls: list[float]) -> float:
    """Maximum drawdown from the cumulative P&L curve.

    Returns the largest peak-to-trough decline as a positive number.
    """
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd
