# ForgeTrade — Automated Forex & Commodities Trading Bot

ForgeTrade is an autonomous trading system built on the OANDA v20 REST API. It runs multiple independent trading strategies simultaneously across forex pairs and commodities, with a real-time web dashboard, risk management, and a paper-trading mode for forward-testing.

The project was built from scratch using the Forge contract-driven development framework — every feature planned, tested, and committed in sequential phases with full audit trails.

---

## What It Does

ForgeTrade connects to your OANDA brokerage account and monitors markets 24/5. When its strategies detect a high-probability setup, it calculates position size based on your risk parameters and places the trade automatically. Each strategy targets a different market condition:

| Strategy | Instruments | Condition | Win Rate Target | Timeframes |
|----------|------------|-----------|-----------------|------------|
| **S/R Rejection** | EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD, NZD/USD, USD/CAD | Swing — rejection wicks at Daily support/resistance zones | 55-60% at 1:2 R:R | D + H4 |
| **Momentum Scalp** | XAU/USD | Momentum — M5 candle bias detection + pullback entries | 60-66% | H1 + M5 + M1 |
| **Mean Reversion** | EUR/USD | Range — oversold/overbought at Bollinger Band extremes in ranging markets | 68-75% at 1:1 R:R | H1 + M15 |

The bot polls OANDA at configurable intervals (60s for scalping, 2-5 min for swing/MR), evaluates its strategy pipeline, and either places a trade or logs why it didn't. Everything is visible on the dashboard.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  forge.json — stream configuration                           │
│  Defines instruments, strategies, timeframes, risk, sessions │
└───────────────┬──────────────────────────────────────────────┘
                │
         ┌──────▼──────┐
         │ EngineManager│  Manages N concurrent trading streams
         └──────┬──────┘
                │
    ┌───────────┼───────────┐
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────┐
│Stream 1│ │Stream 2│ │Stream 3│   Each stream = 1 TradingEngine
│sr-swing│ │micro-  │ │mr-range│   with its own strategy instance
│EUR/USD │ │scalp   │ │EUR/USD │
│        │ │XAU/USD │ │        │
└───┬────┘ └───┬────┘ └───┬────┘
    │          │          │
    ▼          ▼          ▼
┌─────────────────────────────────┐
│         OandaClient             │  Async HTTP with retry/backoff
│  fetch_candles · place_order    │  Dynamic precision per instrument
│  get_positions · get_account    │
└─────────────────────────────────┘
                │
         ┌──────▼──────┐
         │  OANDA v20  │  REST API (practice or live)
         └─────────────┘

         ┌──────────────────────────┐
         │  FastAPI + Dashboard     │  Embedded web server
         │  /status · /trades       │  React + TypeScript + Vite
         │  /signals/history        │  5-second auto-refresh + HMR
         └──────────────────────────┘
```

---

## Strategies in Detail

### S/R Rejection (Phase 2-3, updated)

A swing strategy that identifies horizontal support/resistance zones from 50 Daily candles' swing highs/lows, then watches 60 H4 candles for rejection wick patterns near those zones.

**Entry logic — dynamic zone role:**

Trade direction is determined by where the H4 candle **closes** relative to the zone, not by the zone's original classification (support vs resistance). This captures S/R role-reversal automatically:

- Price closes **above** a zone → zone acts as **support** → bullish rejection wick → **buy**
- Price closes **below** a zone → zone acts as **resistance** → bearish rejection wick → **sell**

For example, if price breaks above a former resistance level and pulls back to retest it, the strategy sees "price above zone → support → look for a buy wick" instead of blindly selling at the old resistance tag. The signal reason distinguishes between original and flipped zones (e.g. "Bullish rejection wick at flipped support 1.18061").

**Rejection wick qualification:**

A rejection wick must have a shadow ≥ 1.0× the candle body (previously 0.5×). This filters out ambiguous candles — a real institutional rejection wick is pronounced, with the shadow at least as long as the body. Dojis are treated as pure wick.

**Zone detection:**

Swing highs/lows are identified using a ±3 candle window, then clustered within 20 pips tolerance into zones. Each zone has a `strength` (touch count) — the `evaluate_signal()` function supports a `min_strength` parameter to filter noise-level zones.

**Risk management (zone-anchored):**

| Parameter | Value |
|-----------|-------|
| TP | Next S/R zone in the profit direction (structural target) |
| SL | TP distance ÷ R:R ratio (guarantees minimum R:R by construction) |
| SL floor | 0.5 × ATR(14) — prevents absurdly tight stops |
| SL cap | 2.0 × ATR(14) — prevents absurdly wide stops (R:R improves beyond target) |
| Min TP distance | 1.0 × ATR(14) — filters noise-level zones |
| No valid zone | ATR fallback: SL = 2×ATR, TP = R:R × SL distance |
| Zone too close | Trade skipped (derived SL below floor) |
| TP zone exclusion | The triggering zone is excluded from TP candidates |
| Position size | 1.0% equity risk per trade (configurable per-stream) |
| R:R ratio | 2.0 (configurable per-stream via dashboard) |
| Max positions | 1 concurrent on EUR/USD |

**H4 trend filter:**

The strategy uses H4 EMA(21)/EMA(50) crossover + price position to classify the trend as bullish, bearish, or flat. Counter-trend signals are **blocked** — a bullish trend suppresses sell signals, a bearish trend suppresses buy signals. Flat trends allow both directions. This prevents entries against strong directional moves (e.g. selling at a resistance wick while price is breaking out above it).

**Dashboard insight:**

The strategy insight panel shows H4 trend context (direction + EMA values), nearest zone distance, zone role analysis (original vs acting-as), rejection wick detection status, and full signal details when found.

| Data | Timeframe | Count |
|------|-----------|-------|
| Daily candles (zones + ATR) | D | 50 |
| H4 candles (signal + trend) | H4 | 60 |

---

### Momentum Scalp (Phase 10-11)

A momentum strategy for XAU/USD (gold) on the M5/M1 timeframe pair. Counts bullish vs bearish M5 candles over the last 15 bars (~75 min window) to establish directional bias, then looks for pullback-to-EMA(9) confirmation patterns with M1 precision timing.

**Entry pipeline:**

1. **M5 momentum bias** — count bullish vs bearish candles over the last 15 M5 bars. If ≥60% are bullish AND net price change ≥ 1 pip → bias = bullish (and vice versa). If neither threshold is met → flat → no trade.
2. **ATR volatility gate** — M5 ATR(14) must be ≥ 80 pips ($0.80). If ATR is below this threshold the market is consolidating — skip entry.
3. **Session-end buffer** — no new entries within 30 minutes of session close (e.g., after 20:30 UTC when session ends at 21:00). Scalps need time to play out.
4. **Spread gate** — the tightest M1 candle's range is used as a spread proxy. If estimated spread > 8 pips → skip (gold spreads widen during low-liquidity periods).
5. **Pullback + confirmation** — price must be near M5 EMA(9), then show a confirmation pattern in the bias direction. Patterns checked (with-bias only, no counter-trend):
   - Bullish engulfing / bearish engulfing
   - Hammer / shooting star
   - Bullish/bearish pin bar
   - Two consecutive same-direction candles (momentum continuation)
   - Single strong-body candle (≥60% of range)

**Risk management:**

| Parameter | Value |
|-----------|-------|
| SL | Recent M5 swing low/high (±2 bar window) + 30 pip ($0.30) buffer |
| SL bounds | Min 200 pips ($2.00), max 800 pips ($8.00) — M5 swings are structural |
| TP | Fixed 1.5:1 R:R from entry |
| Trailing stop | Breakeven at 1×R, trail at 0.5×R behind price at 1.5×R |
| Position size | 2.0% equity risk per trade (configurable per-stream) |
| Max positions | 3 concurrent on XAU/USD |
| Session window | 07:00-21:00 UTC (London + NY overlap) |

**Dashboard insight:**

Multi-timeframe trend snapshot cycles through S5, M1, M5, M15, M30, H1 with EMA(21/50) direction and slope. Shows current spread estimate, EMA(9) distance, momentum bias details, and signal pattern when found.

| Data | Timeframe | Count |
|------|-----------|-------|
| M5 candles (bias + pullback + SL) | M5 | 20 |
| M1 candles (spread + confirm) | M1 | 20 |
| Multi-TF trend snapshots | S5-H1 | 50 each |

---

### Mean Reversion (Phase 12)

The highest-precision strategy. Targets range-bound conditions on EUR/USD using a four-gate entry system plus an H4 trend filter — all gates must align for a trade. Currently disabled in `forge.json` pending forward-testing.

**Entry gates (ALL required):**

1. **ADX(14) < 25** on H1 — confirms the market is ranging, not trending. If ADX ≥ 25, the strategy exits immediately without checking further gates.
2. **Price at Bollinger Band edge** on M15 — price must be ≤ lower BB (oversold) or ≥ upper BB (overbought). Uses BB(20, 2σ).
3. **RSI(14) extreme** on M15 — RSI < 30 (oversold, buy) or RSI > 70 (overbought, sell). Must agree with the BB direction.
4. **S/R zone proximity** — price must be within 15 pips of a structural support (for buys) or resistance (for sells) detected from H1 candles.

**H4 trend filter (shared with S/R Rejection):**

Before placing a trade, the strategy checks H4 EMA(21)/EMA(50) trend direction. Counter-trend signals are **blocked** — if the H4 trend is bearish, buy signals are suppressed; if bullish, sell signals are suppressed. Flat trends allow both directions. This prevents mean-reversion entries against strong directional moves where the "range" may actually be the start of a breakout.

**Risk management:**

| Parameter | Value |
|-----------|-------|
| SL | Beyond the range boundary (zone + ATR buffer), bounded 10-50 pips |
| TP | Bollinger Band midpoint (BB middle line) — conservative, targets mean |
| Position size | 0.75% equity risk per trade |
| Max positions | 1 concurrent on EUR/USD |
| Session window | 00:00-24:00 UTC |

**Dashboard insight:**

Shows ADX value with range/trending classification, RSI with oversold/overbought status, all three Bollinger Band levels, nearest S/R zone distance, and which gate(s) are failing when no signal fires.

| Data | Timeframe | Count |
|------|-----------|-------|
| H4 candles (trend filter) | H4 | 60 |
| H1 candles (ADX + zones) | H1 | 50 |
| M15 candles (RSI + BB) | M15 | 30 |

---

## Risk Management

| Control | Description |
|---------|-------------|
| **Position sizing** | Risk-based: calculates units from `risk_per_trade_pct`, SL distance, and account balance |
| **Max concurrent positions** | Per-stream limit (e.g. 1 for swing, 3 for scalp) |
| **Circuit breaker** | Global max drawdown (10%) — halts all trading if breached |
| **Session window** | Per-stream UTC hour filter (forex 0-24, gold 7-21) |
| **Session-end buffer** | No new scalp entries within 30 min of session close |
| **Trailing stop** | Scalp trades: breakeven at 1×R, trail at 0.5×R behind price at 1.5×R |
| **Account-level drawdown** | Aggregated worst drawdown across all streams, displayed on dashboard |
| **SL/TP on every trade** | No trade is placed without a stop-loss and take-profit |

---

## Dashboard

The dashboard is a React + TypeScript single-page app built with Vite. During development, Vite's dev server provides instant hot module replacement (HMR) — every code change reflects immediately in the browser without restarting anything.

**Tech stack:** React 19 · TypeScript · Vite 7 · CSS custom properties (dark theme)

**Features:**

- **Account summary** — equity, balance, unrealised P&L, account-level drawdown bar, circuit breaker status
- **Open positions** — live trades with entry, SL, TP, current P&L
- **Trade history** — closed trades with P&L, close reason badges (TP/SL/manual), duration
- **Stream status** — strategy label (SR Swing / Scalp / MR), instrument, status, last signal time, per-stream pause/resume buttons
- **Strategy insight** — per-stream analysis panel with entry readiness checklist, zone maps, trend analysis, and signal details (swing + scalp renderers)
- **Signal log** — last 50 signal evaluations with reasons and status badges, collapsed preview
- **Controls** — pause/resume all streams, per-stream pause/resume, emergency stop
- **Settings** — risk %, R:R, max drawdown, session hours, poll interval (persisted to `forge.json`)
- **Drag-to-reorder cards** — drag any card to rearrange the layout, order saved to localStorage
- **Collapsible cards** — collapse state persisted to localStorage

Auto-polls every 5 seconds. Fully responsive. All API calls proxied through Vite in dev, served by FastAPI in production.

### Development

```bash
cd dashboard
npm install        # first time only
npm run dev        # starts Vite dev server on http://localhost:5173
                   # API requests proxy to FastAPI on :8080
```

Any change to `dashboard/src/` files hot-reloads instantly — no restart needed.

### Production build

```bash
cd dashboard
npm run build      # outputs to app/static/dist/
```

FastAPI serves the built files automatically from `http://localhost:8080/`.

---

## Project Structure

```
Forge/
├── forge.json                    # Stream & strategy configuration
├── pytest.ini                    # Test configuration
├── requirements.txt              # Python dependencies
│
├── app/
│   ├── main.py                   # Entry point (paper/live/backtest modes)
│   ├── config.py                 # Environment variable loader
│   ├── engine.py                 # TradingEngine — per-stream trading loop
│   ├── engine_manager.py         # EngineManager — multi-stream orchestration
│   │
│   ├── api/
│   │   └── routers.py            # FastAPI endpoints (/status, /trades, /signals)
│   │
│   ├── broker/
│   │   ├── models.py             # OANDA response dataclasses
│   │   └── oanda_client.py       # Async OANDA v20 client with retry
│   │
│   ├── strategy/
│   │   ├── base.py               # StrategyProtocol + StrategyResult
│   │   ├── registry.py           # Strategy name → class mapping
│   │   ├── models.py             # CandleData, SRZone, EntrySignal, pip values
│   │   ├── indicators.py         # ATR, EMA, RSI, ADX, Bollinger Bands
│   │   ├── sr_zones.py           # Support/resistance zone detection
│   │   ├── signals.py            # S/R rejection wick signal evaluation
│   │   ├── session_filter.py     # UTC session window filter
│   │   ├── spread_filter.py      # Spread gate (low-liquidity filter)
│   │   ├── sr_rejection.py       # S/R Rejection strategy class
│   │   ├── mr_signals.py         # Mean reversion entry signal evaluation
│   │   ├── trend.py              # Trend/bias detection (EMA + M5 candle counting)
│   │   ├── trend_scalp.py        # Momentum Scalp strategy class
│   │   ├── scalp_signals.py      # Scalp entry signal evaluation
│   │   └── mean_reversion.py     # Mean Reversion strategy class + is_ranging()
│   │
│   ├── risk/
│   │   ├── position_sizer.py     # Risk-based position sizing
│   │   ├── sl_tp.py              # Zone-anchored SL/TP for S/R rejection
│   │   ├── scalp_sl_tp.py        # SL/TP for momentum scalp strategy
│   │   ├── mr_sl_tp.py           # SL/TP for mean reversion strategy
│   │   ├── trailing_stop.py      # Trailing stop logic (breakeven + trail)
│   │   └── drawdown.py           # Circuit breaker (max drawdown tracker)
│   │
│   ├── backtest/
│   │   ├── engine.py             # Backtest replay engine
│   │   └── stats.py              # Backtest statistics calculator
│   │
│   ├── repos/
│   │   ├── db.py                 # SQLite connection manager
│   │   ├── trade_repo.py         # Trade persistence
│   │   ├── equity_repo.py        # Equity curve persistence
│   │   └── backtest_repo.py      # Backtest run persistence
│   │
│   ├── cli/
│   │   └── dashboard.py          # Terminal CLI dashboard
│   │
│   └── static/
│       ├── index.html            # Legacy web dashboard (fallback)
│       └── dist/                 # Vite production build output
│
├── dashboard/                    # React + TypeScript + Vite frontend
│   ├── package.json              # Node.js dependencies & scripts
│   ├── tsconfig.json             # TypeScript configuration
│   ├── vite.config.ts            # Vite config with API proxy
│   └── src/
│       ├── main.tsx              # React entry point
│       ├── App.tsx               # Root component (polling, layout, drag-reorder)
│       ├── index.css             # Global styles (CSS custom properties, dark theme)
│       ├── types.ts              # API response TypeScript interfaces
│       ├── api.ts                # Typed fetch wrappers (account, streams, control)
│       ├── hooks.ts              # usePolling, useLocalStorage hooks
│       ├── helpers.ts            # Formatting utilities (currency, %, PnL)
│       ├── vite-env.d.ts         # Vite type declarations
│       └── components/           # 13 React components
│
├── tests/
│   ├── test_config.py            # Config loader tests
│   ├── test_broker.py            # OANDA client tests
│   ├── test_strategy.py          # S/R zones, signals, session filter tests
│   ├── test_risk.py              # Position sizing, SL/TP, drawdown tests
│   ├── test_engine.py            # Trading engine tests
│   ├── test_engine_manager.py    # Engine manager tests
│   ├── test_backtest.py          # Backtest engine tests
│   ├── test_health.py            # Health endpoint tests
│   ├── test_dashboard_api.py     # Dashboard route tests
│   ├── test_phase4.py            # API endpoint tests
│   ├── test_integration.py       # Cross-module integration tests
│   ├── test_strategy_abstraction.py # Strategy protocol/registry tests
│   ├── test_trend_scalp.py       # Momentum scalp + bias tests
│   └── test_mean_reversion.py    # RSI, ADX, Bollinger, MR signal tests
│
├── Contracts/                    # Forge governance layer
│   ├── blueprint.md              # Project blueprint
│   ├── manifesto.md              # Non-negotiable principles
│   ├── phases.md                 # Phase-by-phase build plan (0-12)
│   ├── schema.md                 # Data model specification
│   ├── stack.md                  # Technology stack definition
│   ├── physics.yaml              # API specification
│   ├── boundaries.json           # Layer boundaries
│   ├── ui.md                     # Dashboard specification
│   └── directive.md              # Builder priming document
│
├── scripts/
│   ├── boot.ps1                  # One-click launcher
│   ├── run_tests.ps1             # Test runner
│   ├── run_audit.ps1             # Audit gate checker
│   ├── overwrite_diff_log.ps1    # Diff log management
│   └── setup_checklist.ps1       # Post-build setup guide
│
├── db/migrations/
│   └── 001_initial_schema.sql    # SQLite schema
│
└── evidence/
    ├── audit_ledger.md           # Append-only audit evidence
    └── test_runs.md              # Test run logs
```

---

## Setup

### Prerequisites

- Python 3.12+
- An OANDA practice or live account
- OANDA API key (v20 REST)

### Installation

```bash
git clone <repo-url> && cd ForgeTrade/Forge
python -m venv ../.venv
../.venv/Scripts/activate      # Windows
pip install -r requirements.txt
```

### Configuration

Create a `.env` file in the `Forge/` directory:

```env
OANDA_API_KEY=your-api-key-here
OANDA_ACCOUNT_ID=your-account-id
OANDA_BASE_URL=https://api-fxpractice.oanda.com   # practice
# OANDA_BASE_URL=https://api-fxtrade.oanda.com    # live
```

### Running

```powershell
# One-click launch (recommended)
.\scripts\boot.ps1

# Or manually:
python -m app.main              # Paper mode (default)
python -m app.main --live       # Live mode
python -m app.main --backtest   # Backtest mode
```

The dashboard is available at `http://localhost:8080` when running in paper or live mode.

### Running Tests

```powershell
python -m pytest -v             # Full suite (225+ tests)
python -m pytest tests/test_mean_reversion.py -v   # Specific module
```

---

## Stream Configuration

Trading streams are defined in `forge.json`. Each stream runs independently with its own strategy, instrument, timeframes, and risk parameters:

```json
{
  "name": "sr-swing",
  "instrument": "EUR_USD",
  "strategy": "sr_rejection",
  "timeframes": ["D", "H4"],
  "poll_interval_seconds": 300,
  "risk_per_trade_pct": 1.0,
  "max_concurrent_positions": 1,
  "session_start_utc": 0,
  "session_end_utc": 24,
  "enabled": true
}
```

Currently configured streams:

| Stream | Instrument | Strategy | Poll Interval | Risk | Status |
|--------|-----------|----------|---------------|------|--------|
| `sr-swing` | EUR/USD | S/R Rejection | 5 min | 1.0% | Enabled |
| `micro-scalp` | XAU/USD | Momentum Scalp | 60s | 2.0% | Enabled |
| `mr-range` | EUR/USD | Mean Reversion | 2 min | 0.75% | Disabled |
| `sr-gbp` | GBP/USD | S/R Rejection | 5 min | 1.0% | Enabled |
| `sr-jpy` | USD/JPY | S/R Rejection | 5 min | 1.0% | Enabled |
| `sr-chf` | USD/CHF | S/R Rejection | 5 min | 1.0% | Enabled |
| `sr-aud` | AUD/USD | S/R Rejection | 5 min | 1.0% | Enabled |
| `sr-nzd` | NZD/USD | S/R Rejection | 5 min | 1.0% | Enabled |
| `sr-cad` | USD/CAD | S/R Rejection | 5 min | 1.0% | Enabled |

---

## Technical Indicators

All indicators are pure functions in `app/strategy/indicators.py` with no side effects:

| Indicator | Function | Default Period | Used By |
|-----------|----------|---------------|---------|
| ATR | `calculate_atr()` | 14 | All strategies (SL/TP sizing) |
| EMA | `calculate_ema()` | configurable | Trend detection, dashboard |
| RSI | `calculate_rsi()` | 14 | Mean Reversion (oversold/overbought) |
| ADX | `calculate_adx()` | 14 | Mean Reversion (range vs trend filter) |
| Bollinger Bands | `calculate_bollinger()` | 20, 2σ | Mean Reversion (range boundary) |

---

## Build History

The project was built in sequential phases using the Forge contract-driven framework:

| Phase | Description | Tests Added |
|-------|-------------|-------------|
| 0 | Genesis — project scaffold, scripts, configs | — |
| 1 | OANDA broker client, config loader, typed models | 11 |
| 2 | Strategy engine — S/R zones, signals, session filter, ATR | 10 |
| 3 | Risk manager — position sizer, SL/TP, drawdown, engine | 20 |
| 4 | Trade logging, API endpoints, CLI dashboard | 10 |
| 5 | Backtest engine, stats calculator | 7 |
| 6 | Paper & live integration, polling loop, signal handler | 5 |
| 7 | Web dashboard — FastAPI endpoints + static HTML | — |
| 8 | Strategy abstraction — StrategyProtocol, plugin registry | — |
| 9 | Multi-stream engine manager | — |
| 10 | Trend-confirmed micro-scalp for XAU/USD | — |
| 11 | Momentum bias replaces EMA crossover trend gate | 7 |
| 12 | Mean reversion strategy for EUR/USD ranging markets | 41 |
| 13-33 | Dashboard overhaul (React+TS+Vite), stream expansion (7 FX pairs), per-stream settings, gold scalp upgrades, SL buffer fixes, volatility gate, session filters, signal log, trade history filters | — |
| 34 | SR SL/TP investigation — fixed `calculate_tp` min R:R fallback, H4 trend visibility | — |
| 35 | Zone-anchored TP rewrite — TP targets next S/R zone, SL derived from R:R | 11 |
| 36 | Streams table overhaul — strategy labels, per-stream pause/resume, last signal fix, ghost stream removal | — |
| 37 | Account-level drawdown — aggregated across all streams, wired to dashboard | — |
| **Total** | | **225 passing** |

---

## License

MIT
