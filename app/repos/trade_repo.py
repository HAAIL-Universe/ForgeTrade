"""Trade repository — SQLite CRUD for the trades table."""

import sqlite3
from datetime import datetime, timezone
from typing import Optional

from app.repos.db import get_connection


class TradeRepo:
    """Data access layer for trade records.

    Args:
        db_path: Path to the SQLite database file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    # ── Write ────────────────────────────────────────────────────────────

    def insert_trade(
        self,
        mode: str,
        direction: str,
        pair: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        units: float,
        sr_zone_price: float,
        sr_zone_type: str,
        entry_reason: str,
        opened_at: str,
    ) -> int:
        """Insert a new open trade and return its ``id``."""
        conn = get_connection(self._db_path)
        try:
            cur = conn.execute(
                """
                INSERT INTO trades
                    (mode, direction, pair, entry_price, stop_loss,
                     take_profit, units, sr_zone_price, sr_zone_type,
                     entry_reason, opened_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mode, direction, pair, entry_price, stop_loss,
                    take_profit, units, sr_zone_price, sr_zone_type,
                    entry_reason, opened_at,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        exit_reason: str,
        pnl: float,
    ) -> None:
        """Close an open trade by setting exit fields."""
        closed_at = datetime.now(timezone.utc).isoformat()
        conn = get_connection(self._db_path)
        try:
            conn.execute(
                """
                UPDATE trades
                SET exit_price = ?, exit_reason = ?, pnl = ?,
                    status = 'closed', closed_at = ?
                WHERE id = ?
                """,
                (exit_price, exit_reason, pnl, closed_at, trade_id),
            )
            conn.commit()
        finally:
            conn.close()

    # ── Read ─────────────────────────────────────────────────────────────

    def get_trades(
        self,
        limit: int = 20,
        status_filter: Optional[str] = None,
    ) -> dict:
        """Return recent trades as a dict matching the physics.yaml schema.

        Returns:
            ``{"trades": [...], "total": int}``
        """
        conn = get_connection(self._db_path)
        try:
            if status_filter:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE status = ? ORDER BY id DESC LIMIT ?",
                    (status_filter, limit),
                ).fetchall()
                total = conn.execute(
                    "SELECT COUNT(*) FROM trades WHERE status = ?",
                    (status_filter,),
                ).fetchone()[0]
            else:
                rows = conn.execute(
                    "SELECT * FROM trades ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]

            trades = [dict(row) for row in rows]
            return {"trades": trades, "total": total}
        finally:
            conn.close()
