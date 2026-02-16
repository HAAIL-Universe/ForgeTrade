# ForgeTrade — UI/UX Blueprint

## Dashboard

ForgeTrade serves a single-page dark-themed web dashboard via FastAPI's `StaticFiles` mount. The dashboard is one HTML file with inline CSS and vanilla JavaScript — no framework, no build step, no npm.

**URL:** `http://localhost:{HEALTH_PORT}/dashboard/index.html` (root `/` redirects here)

### Interaction Model

- **Read-only** — the dashboard does not place or modify trades.
- **Polling** — fetches data via `fetch()` every 5 seconds. No WebSockets.
- **Single page** — all sections visible at once, no navigation.

### Sections

1. **Header Bar** — Mode badge (PAPER / LIVE / BACKTEST), uptime.
2. **Account Metrics** — Equity, balance, drawdown percentage with colour bar, circuit breaker status.
3. **Open Positions Table** — Pair, direction, units, entry, SL, TP, unrealized P&L.
4. **Watchlist Panel** — Last evaluated signal: pair, direction, zone, reason, status.
5. **Closed Trades Table** — Today's closed trades with P&L per trade and running total.
6. **Streams Table** — Per-stream status: name, instrument, cycle count, status dot, last signal time.

### Theme

- Background: `#0d1117`
- Card surfaces: `#161b22`
- Text: `#c9d1d9`
- Borders: `#30363d`
- Font: `"JetBrains Mono", "Fira Code", monospace` for numbers; system sans-serif for labels.

### Colour Rules

- Equity delta / P&L: green if positive, red if negative.
- Drawdown bar: yellow 0–5%, orange 5–8%, red 8%+.
- Circuit breaker: green "OFF", pulsing red "ACTIVE".
- Mode badge: blue = PAPER, red with glow = LIVE, purple = BACKTEST.
- Stream status dot: green = active, grey = off, red = error.

### CLI Dashboard (Legacy)

The original CLI dashboard (`app/cli/dashboard.py`) remains functional for headless/terminal use. User interaction via:

1. **Configuration:** `.env` file and CLI arguments at startup
2. **Monitoring:** Console output in PowerShell terminal
3. **Control:** Start/stop via running/terminating the Python process
