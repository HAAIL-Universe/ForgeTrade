# ForgeTrade — Blueprint (v0.1)

Status: Draft (authoritative for v0.1 build)
Owner: HAAIL-Universe
Purpose: Define product fundamentals, hard boundaries, and build targets so implementation cannot drift.

---

## 1) Product intent

ForgeTrade is an automated trading bot for personal use. It connects to OANDA's v20 REST API and trades multiple instruments using pluggable strategies running as concurrent streams. The primary stream trades EUR/USD on Daily/4H timeframes using S/R rejection wicks. A secondary stream scalps XAU/USD on H1/M1/S5 timeframes using trend-confirmed pullbacks. A dark-themed web dashboard displays real-time bot state, open positions, pending signals, and closed trade P&L.

The bot operates as a "set and forget" system — the user starts it in a PowerShell terminal, and it runs continuously with a web dashboard for monitoring. It supports three modes: backtest (historical replay), paper (OANDA practice account), and live (OANDA live account).

---

## Core interaction invariants (must hold)

- The bot must NEVER place a live trade unless explicitly started in live mode via configuration.
- Every trade entry, exit, and P&L must be logged to the local database — no silent trades.
- The bot must halt all trading if the 10% max drawdown circuit breaker is triggered.
- Strategy logic must be pure and deterministic — same candle data in = same signal out, always.
- Paper and live modes use identical strategy and risk logic — only the OANDA endpoint differs.

---

## 2) MVP scope (v0.1)

### Must ship

1. **OANDA Broker Client**
   - Connect to OANDA v20 REST API (practice and live endpoints, config-driven)
   - Fetch Daily and 4H candle data for EUR/USD
   - Query account balance and open positions
   - Place market orders with stop-loss and take-profit
   - Close positions

2. **S/R Zone Detection**
   - Identify horizontal support and resistance zones from swing highs/lows on the Daily timeframe
   - Lookback: ~50 candles
   - Zones stored and updated periodically

3. **Entry Signal Engine**
   - Drop to 4H timeframe for entry timing
   - Detect when price touches an S/R zone and the next 4H candle closes with a rejection wick (wick length > 50% of candle body)
   - Direction: buy at support, sell at resistance (bounce trades only)
   - Session filter: only trade during London + New York sessions (07:00–21:00 UTC)

4. **Risk Manager**
   - Position sizing: risk 1% of account equity per trade
   - Stop loss: 1.5× ATR(14) beyond the S/R zone
   - Take profit: next S/R zone or 1:2 risk-reward ratio, whichever comes first
   - Maximum drawdown limit: 10% from peak equity — bot stops trading if breached
   - No martingale, no grid, no averaging down

5. **Trade Logging**
   - Every entry, exit, and P&L logged to SQLite
   - Equity snapshots recorded periodically

6. **CLI Dashboard**
   - Console output showing: bot status, open positions, current equity, daily P&L, last signal check, drawdown status
   - Runs in PowerShell terminal

7. **Backtest Engine**
   - Replay historical 4H and Daily candles through the strategy
   - Produce stats: win rate, profit factor, Sharpe ratio, max drawdown
   - Output results to console and/or file

8. **Minimal Internal API**
   - FastAPI server on localhost (for Forge verification gates and dashboard)
   - `GET /health` returns `{"status": "ok"}`
   - `GET /status` returns bot state (mode, equity, open positions, drawdown, per-stream status)
   - `GET /positions` returns current open positions from OANDA
   - `GET /signals/pending` returns the last evaluated signal (watchlist)
   - `GET /trades` returns trade log with optional stream filter
   - `GET /trades/closed` returns closed trades with P&L

9. **Web Dashboard**
   - Single-page dark-themed HTML dashboard served by FastAPI at `/dashboard/`
   - Displays: account metrics, open positions, watchlist, closed trades, stream status
   - Auto-refreshes via polling every 5 seconds
   - Read-only — no trade placement from the dashboard
   - No JavaScript framework, no npm, no build step

10. **Strategy Abstraction**
    - Pluggable strategy interface (`StrategyProtocol`)
    - S/R Rejection Wick strategy extracted into its own class
    - EMA indicator added to indicator library
    - Per-instrument pip values

11. **Multi-Stream Engine**
    - `EngineManager` runs multiple `TradingEngine` instances concurrently via `asyncio.gather()`
    - Each stream has its own instrument, strategy, timeframes, and polling interval
    - Streams configured declaratively in `forge.json`
    - Single OANDA account shared across streams

12. **Trend-Confirmed Micro-Scalp Strategy (XAU/USD)**
    - H1 trend gate (EMA21/EMA50), M1 entry, S5 precision timing
    - Swing-structure SL, fixed 1:1.5 R:R TP
    - Trailing stop (breakeven at 1R, trail at 1.5R)
    - Spread filter to reject wide-spread entries
    - Position count guard (max concurrent configurable per stream)

### Explicitly not MVP (v0.1)

- No strategy optimization or parameter tuning
- No email/SMS/push notifications
- No multi-user support
- No Docker containerization
- No cloud deployment

---

## 3) Hard boundaries (anti-godfile rules)

### Entry / CLI layer
- Boots the bot, parses config/CLI args, starts the async event loop and internal API server
- Prints console output (CLI dashboard)
- Must NOT contain strategy logic, broker API calls, DB queries, or risk calculations

### Strategy layer
- Detects S/R zones, evaluates entry signals, applies session filter
- Pure functions: takes candle data in, returns signals out
- Must NOT make broker API calls, write to DB, or access config/environment directly

### Broker client layer
- All OANDA v20 REST API communication: fetching candles, placing orders, querying account
- Must NOT contain strategy logic, risk calculations, or DB access

### Risk manager layer
- Position sizing, SL/TP calculation, drawdown tracking, trade gating
- Must NOT make broker API calls or DB writes directly

### Repository / DAL layer
- All SQLite reads and writes: trade log, equity snapshots, S/R zone cache
- Must NOT contain strategy logic, broker calls, or risk calculations

---

## 4) Deployment target

- Target: Local machine (Windows, PowerShell terminal)
- Expected users: 1 (personal use)
- Runs as a long-lived Python process started from PowerShell
- Config via `.env` file and CLI arguments
