"""Backtest run repository — persists backtest summaries to SQLite."""

import sqlite3

from app.repos.db import get_connection


class BacktestRepo:
    """Data access layer for the ``backtest_runs`` table.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def insert_run(
        self,
        pair: str,
        start_date: str,
        end_date: str,
        stats: dict,
    ) -> int:
        """Persist a backtest run summary.  Returns the row id."""
        conn = get_connection(self._db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO backtest_runs
                    (pair, start_date, end_date, total_trades,
                     winning_trades, losing_trades, win_rate,
                     profit_factor, sharpe_ratio, max_drawdown, net_pnl)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pair,
                    start_date,
                    end_date,
                    stats["total_trades"],
                    stats["winning_trades"],
                    stats["losing_trades"],
                    stats["win_rate"],
                    stats.get("profit_factor"),
                    stats["sharpe_ratio"],
                    stats["max_drawdown"],
                    stats["net_pnl"],
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_runs(self, limit: int = 10) -> list[dict]:
        """Return recent backtest run summaries."""
        conn = get_connection(self._db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM backtest_runs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
