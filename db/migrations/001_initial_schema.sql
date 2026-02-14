-- Migration: 001
-- ForgeTrade initial schema (v0.1)
-- SQLite SQL — executed on first boot by the app's startup routine.

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
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_opened_at ON trades(opened_at);
CREATE INDEX idx_trades_mode ON trades(mode);

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

CREATE INDEX idx_equity_recorded_at ON equity_snapshots(recorded_at);

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

CREATE INDEX idx_sr_zones_pair_type ON sr_zones(pair, zone_type);
CREATE INDEX idx_sr_zones_active ON sr_zones(invalidated_at) WHERE invalidated_at IS NULL;

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
