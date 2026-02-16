-- Migration: 002
-- Add stream_name column to trades table for multi-stream support.

ALTER TABLE trades ADD COLUMN stream_name TEXT DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_trades_stream ON trades(stream_name);
