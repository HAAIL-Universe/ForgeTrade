"""Database initialization and connection management.

Runs migrations on first boot, provides connection factory.
"""

import pathlib
import sqlite3


_MIGRATION_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "db" / "migrations"


def init_db(db_path: str) -> None:
    """Initialize the database by running all migration scripts.

    Safe to call multiple times — uses ``CREATE TABLE IF NOT EXISTS``
    semantics (the migration SQL uses plain ``CREATE TABLE`` but we
    wrap execution so that an already-initialised DB is a no-op).

    Args:
        db_path: Path to the SQLite database file (or ``":memory:"``).
    """
    conn = sqlite3.connect(db_path)
    try:
        # Check if tables already exist
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        )
        if cur.fetchone() is not None:
            return  # Already initialised

        migration_file = _MIGRATION_DIR / "001_initial_schema.sql"
        sql = migration_file.read_text(encoding="utf-8")
        conn.executescript(sql)
    finally:
        conn.close()


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a new SQLite connection with row-factory enabled.

    Callers are responsible for closing the connection.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
