"""Equity snapshot repository — SQLite operations for equity_snapshots table."""

import sqlite3

from app.repos.db import get_connection


class EquityRepo:
    """Data access layer for equity snapshots.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    def insert_snapshot(
        self,
        mode: str,
        equity: float,
        balance: float,
        peak_equity: float,
        drawdown_pct: float,
        open_positions: int,
    ) -> None:
        """Record an equity snapshot."""
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                INSERT INTO equity_snapshots
                    (mode, equity, balance, peak_equity, drawdown_pct, open_positions)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (mode, equity, balance, peak_equity, drawdown_pct, open_positions),
            )
            conn.commit()
        finally:
            conn.close()

    def get_latest(self) -> dict | None:
        """Return the most recent equity snapshot, or ``None``."""
        conn = get_connection(self._db_path)
        try:
            row = conn.execute(
                "SELECT * FROM equity_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
