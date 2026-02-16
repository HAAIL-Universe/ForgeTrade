"""Database initialization and connection management.

Runs migrations on first boot, provides connection factory.
"""

import pathlib
import sqlite3


_MIGRATION_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "db" / "migrations"


def init_db(db_path: str) -> None:
    """Initialize the database by running all migration scripts.

    Runs initial schema if tables don't exist, then applies any
    incremental migrations that haven't been applied yet.

    Args:
        db_path: Path to the SQLite database file (or ``":memory:"``).
    """
    conn = sqlite3.connect(db_path)
    try:
        # Check if tables already exist
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trades'"
        )
        if cur.fetchone() is None:
            # Run initial schema
            migration_file = _MIGRATION_DIR / "001_initial_schema.sql"
            sql = migration_file.read_text(encoding="utf-8")
            conn.executescript(sql)

        # Apply incremental migrations
        _apply_migration_002(conn)
    finally:
        conn.close()


def _apply_migration_002(conn: sqlite3.Connection) -> None:
    """Add ``stream_name`` column to trades table if missing."""
    columns = [
        row[1]
        for row in conn.execute("PRAGMA table_info(trades)").fetchall()
    ]
    if "stream_name" not in columns:
        migration_file = _MIGRATION_DIR / "002_add_stream_name.sql"
        sql = migration_file.read_text(encoding="utf-8")
        conn.executescript(sql)


def get_connection(db_path: str) -> sqlite3.Connection:
    """Return a new SQLite connection with row-factory enabled.

    Callers are responsible for closing the connection.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn
