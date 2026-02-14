# ForgeTrade — UI/UX Blueprint

N/A — CLI-only project.

ForgeTrade has no web frontend. User interaction is via:

1. **Configuration:** `.env` file and CLI arguments at startup
2. **Monitoring:** Console output in PowerShell terminal (bot status, open positions, equity, daily P&L, drawdown, last signal check)
3. **Control:** Start/stop via running/terminating the Python process

The CLI dashboard prints periodic status lines to stdout. Trade events (entry, exit, circuit breaker) are logged to both console and SQLite.
