# ForgeTrade — Setup & Usage Guide

ForgeTrade is a CLI-first automated Forex trading bot. It connects to OANDA's v20 REST API, monitors EUR/USD on Daily and 4H timeframes, and autonomously places trades based on support/resistance zones and rejection wick patterns.

---

## Prerequisites

- **Python 3.11+** installed
- **OANDA account** (practice or live) — [sign up here](https://www.oanda.com/apply/)
- **PowerShell** (Windows default)

---

## 1) Install Dependencies

```powershell
# From the project root (where requirements.txt lives):
cd Z:\ForgeTrade\Forge

# Create a virtual environment (if not already done)
python -m venv ..\.venv

# Activate it
..\.venv\Scripts\Activate.ps1

# Install packages
pip install -r requirements.txt
```

---

## 2) Get Your OANDA API Credentials

1. Log in to [OANDA's hub](https://hub.oanda.com/) (or [fxTrade](https://fxtrade.oanda.com/) for live accounts).
2. Go to **Manage API Access** → **Generate** a personal access token.
3. Copy:
   - **API Token** (the long string)
   - **Account ID** (format: `101-001-XXXXXXXX-001` — found on the account page)
4. Note which environment you're using:
   - `practice` — demo/paper trading (free, no real money)
   - `live` — real money trading

---

## 3) Configure Environment

Copy the example file and fill in your values:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```dotenv
# === REQUIRED ===
OANDA_ACCOUNT_ID=101-001-XXXXXXXX-001     # Your OANDA account ID
OANDA_API_TOKEN=your-api-token-here        # Your OANDA API token
OANDA_ENVIRONMENT=practice                 # "practice" or "live"

# === OPTIONAL (defaults shown) ===
TRADE_PAIR=EUR_USD                         # Instrument to trade
RISK_PER_TRADE_PCT=1.0                     # % of equity risked per trade
MAX_DRAWDOWN_PCT=10.0                      # Circuit breaker threshold
SESSION_START_UTC=7                        # Trading session start (UTC hour)
SESSION_END_UTC=21                         # Trading session end (UTC hour)
DB_PATH=data/forgetrade.db                 # SQLite database path
LOG_LEVEL=INFO                             # DEBUG, INFO, WARNING, ERROR
HEALTH_PORT=8080                           # Internal API port
```

---

## 4) Run the Bot

### Paper Mode (recommended to start)

```powershell
python -m app.main --mode paper
```

The bot will:
- Connect to OANDA's practice API
- Fetch Daily and 4H candles for EUR/USD
- Detect S/R zones and evaluate entry signals
- Place trades via your practice account
- Print status to the console
- Log all trades to SQLite

### Live Mode (real money — use with caution)

```powershell
python -m app.main --mode live
```

**Warning:** A prominent warning will appear and the bot will pause for 5 seconds before starting. This uses real money. Make sure `OANDA_ENVIRONMENT=live` and your API token is for a live account.

### Backtest Mode

```powershell
python -m app.main --mode backtest --start 2024-01-01 --end 2025-01-01
```

Replays historical candles through the strategy and produces stats:
- Win rate, profit factor, Sharpe ratio, max drawdown, net P&L

---

## 5) Stopping the Bot

Press **Ctrl+C** in the terminal. The bot handles this gracefully:
- Logs final state
- Flushes the database
- Exits cleanly (exit code 0)

---

## 6) Internal API (optional)

While the bot is running, a FastAPI server runs on `localhost:{HEALTH_PORT}`:

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Returns `{"status": "ok"}` — health check |
| `GET /status` | Current bot state: mode, equity, drawdown, positions, uptime |
| `GET /trades` | Recent trade log entries |

Example:
```powershell
Invoke-RestMethod http://localhost:8080/status
```

---

## 7) Run Tests

```powershell
pytest
```

Or via the Forge test runner:
```powershell
pwsh -File Forge\scripts\run_tests.ps1
```

---

## Risk Parameters Explained

| Setting | What It Does |
|---------|--------------|
| `RISK_PER_TRADE_PCT=1.0` | Risks 1% of account equity per trade. $10,000 equity → $100 max loss per trade. |
| `MAX_DRAWDOWN_PCT=10.0` | If equity drops 10% from peak, the **circuit breaker** activates and all trading halts. Requires restart to resume. |
| `SESSION_START_UTC=7` / `SESSION_END_UTC=21` | Only trades during London + New York sessions (07:00–21:00 UTC). Signals outside this window are ignored. |

---

## Strategy Overview

1. **S/R Zone Detection**: Scans last 50 Daily candles for swing highs/lows → clusters into support/resistance zones
2. **Entry Signal**: Drops to 4H timeframe. If price touches an S/R zone and the candle closes with a rejection wick (wick > 50% of body) → entry signal
3. **Direction**: Buy at support, sell at resistance (bounce trades only)
4. **Stop Loss**: Placed 1.5× ATR(14) beyond the S/R zone
5. **Take Profit**: Next S/R zone or 1:2 risk-reward ratio, whichever is closer
6. **Position Size**: Calculated to risk exactly `RISK_PER_TRADE_PCT` of equity

---

## Database

Trades and equity snapshots are stored in SQLite at the path specified by `DB_PATH`. The database is auto-created on first boot.

You can query it directly:
```powershell
sqlite3 data/forgetrade.db "SELECT * FROM trades ORDER BY id DESC LIMIT 10;"
```

Tables: `trades`, `equity_snapshots`, `sr_zones`, `backtest_runs`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Missing required environment variable(s)` | Check `.env` — you need `OANDA_ACCOUNT_ID`, `OANDA_API_TOKEN`, and `OANDA_ENVIRONMENT` at minimum |
| `401 Unauthorized` from OANDA | Your API token is wrong or expired. Generate a new one from OANDA hub. |
| `httpx.ConnectError` | Check internet connection. OANDA API may also be down (rare). |
| Circuit breaker activated | Equity dropped 10%+ from peak. Review trades, then restart the bot. |
| No signals generated | Normal — the strategy only triggers when price touches an S/R zone with a rejection wick during London/NY hours. Can be quiet for days. |
