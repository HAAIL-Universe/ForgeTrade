# ForgeTrade — Database Schema

Canonical database schema for this project. The builder contract (§1) requires reading this file before making changes. All migrations must implement this schema. No tables or columns may be added without updating this document first.

---

## Schema Version: 0.1 (initial)

### Conventions

- Table names: snake_case, plural
- Column names: snake_case
- Primary keys: INTEGER AUTOINCREMENT
- Timestamps: TEXT (ISO 8601 format, UTC)
- Soft delete: No

---

## Tables

### trades

Records every trade the bot opens and closes. One row per trade lifecycle.

```sql
CREATE TABLE trades (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT NOT NULL CHECK(mode IN ('backtest', 'paper', 'live')),
    direction       TEXT NOT NULL CHECK(direction IN ('buy', 'sell')),
    pair            TEXT NOT NULL DEFAULT 'EUR_USD',
    entry_price     REAL NOT NULL,
    exit_price      REAL,
    stop_loss       REAL NOT NULL,
    take_profit     REAL NOT NULL,
    units           REAL NOT NULL,
    sr_zone_price   REAL NOT NULL,
    sr_zone_type    TEXT NOT NULL CHECK(sr_zone_type IN ('support', 'resistance')),
    entry_reason    TEXT NOT NULL,
    exit_reason     TEXT,
    pnl             REAL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open', 'closed', 'cancelled')),
    opened_at       TEXT NOT NULL,
    closed_at       TEXT,
    stream_name     TEXT DEFAULT 'default',
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

```sql
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_opened_at ON trades(opened_at);
CREATE INDEX idx_trades_mode ON trades(mode);
CREATE INDEX idx_trades_stream ON trades(stream_name);
```

---

### equity_snapshots

Periodic snapshots of account equity for drawdown tracking and reporting.

```sql
CREATE TABLE equity_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    mode            TEXT NOT NULL CHECK(mode IN ('backtest', 'paper', 'live')),
    equity          REAL NOT NULL,
    balance         REAL NOT NULL,
    peak_equity     REAL NOT NULL,
    drawdown_pct    REAL NOT NULL,
    open_positions  INTEGER NOT NULL DEFAULT 0,
    recorded_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
```

```sql
CREATE INDEX idx_equity_recorded_at ON equity_snapshots(recorded_at);
```

---

### sr_zones

Cached support/resistance zones detected from Daily candles.

```sql
CREATE TABLE sr_zones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pair            TEXT NOT NULL DEFAULT 'EUR_USD',
    zone_type       TEXT NOT NULL CHECK(zone_type IN ('support', 'resistance')),
    price_level     REAL NOT NULL,
    strength        INTEGER NOT NULL DEFAULT 1,
    detected_at     TEXT NOT NULL,
    invalidated_at  TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

```sql
CREATE INDEX idx_sr_zones_pair_type ON sr_zones(pair, zone_type);
CREATE INDEX idx_sr_zones_active ON sr_zones(invalidated_at) WHERE invalidated_at IS NULL;
```

---

### backtest_runs

Summary records for completed backtest runs.

```sql
CREATE TABLE backtest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pair            TEXT NOT NULL DEFAULT 'EUR_USD',
    start_date      TEXT NOT NULL,
    end_date        TEXT NOT NULL,
    total_trades    INTEGER NOT NULL,
    winning_trades  INTEGER NOT NULL,
    losing_trades   INTEGER NOT NULL,
    win_rate        REAL NOT NULL,
    profit_factor   REAL,
    sharpe_ratio    REAL,
    max_drawdown    REAL NOT NULL,
    net_pnl         REAL NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
```

---

## Migration Files

The builder creates migration files in `db/migrations/` during Phase 0. File naming convention:

```
db/migrations/
  001_initial_schema.sql
  002_add_stream_name.sql
```

Each migration file contains:
- A `-- Migration: NNN` header comment
- `CREATE TABLE` statements (or `ALTER TABLE` for incremental migrations)
- `CREATE INDEX` statements
- No `DROP` statements in initial migrations

The migration files are created during Phase 0 but NOT executed until the bot first starts. They must be valid SQLite SQL that can be run manually or via the app's startup routine.
