# ForgeTrade — Build Phases

This document defines the phased build plan. Each phase is a self-contained unit of work with clear acceptance criteria, verification gates, and scope boundaries.

The builder executes one phase at a time. Each phase must pass the full verification hierarchy (static → runtime → behavior → contract) and the audit script before sign-off.

---

## Phase 0 — Genesis (Bootstrap)

### Purpose

Scaffold the project from an empty folder. Create all directories, configuration files, scripts, and the initial booting application. After Phase 0, the full builder contract enforcement (§1 read gate, audit scripts, verification hierarchy) becomes active.

### Exemptions

- **§1 read gate is SUSPENDED** for this phase only. The contract files don't exist in the repo yet — the builder's job is to place them there.
- **A1 scope compliance:** Claimed files = everything created (the entire initial scaffold).
- **A3 evidence completeness:** `test_runs_latest.md` may report a minimal suite. A skeletal pass is acceptable.
- **A9 dependency gate:** Dependencies are being established; the gate becomes enforced from Phase 1.

### Phase 0 Outputs (all must exist at completion)

| # | Output | Description |
|---|--------|-------------|
| 1 | Directory structure | `app/`, `app/strategy/`, `app/broker/`, `app/risk/`, `app/repos/`, `app/api/`, `app/cli/`, `app/backtest/`, `db/migrations/`, `tests/`, `data/`, `evidence/`, `scripts/`, `Contracts/` |
| 2 | `Contracts/` populated | `blueprint.md`, `manifesto.md`, `stack.md`, `schema.md`, `physics.yaml`, `boundaries.json`, `ui.md` — all provided by director, builder copies them into place |
| 3 | `evidence/` directory | With empty `updatedifflog.md` (will be finalized end of phase) |
| 4 | `scripts/run_tests.ps1` | Copied from Forge, functional for declared stack |
| 5 | `scripts/run_audit.ps1` | Copied from Forge, functional with project's `boundaries.json` |
| 6 | `scripts/overwrite_diff_log.ps1` | Copied from Forge (generic, no customization needed) |
| 7 | `forge.json` | Machine-readable project config (schema defined in `stack.md`) |
| 8 | `.env.example` | From `stack.md` environment variables table (values are examples, not secrets) |
| 9 | `requirements.txt` | Initial dependencies: `fastapi`, `uvicorn`, `httpx`, `pytest`, `python-dotenv` |
| 10 | `db/migrations/001_initial_schema.sql` | From `schema.md` — valid SQLite SQL, NOT executed (no DB connection yet) |
| 11 | App entry point (`app/main.py`) | Boots FastAPI, serves `/health` endpoint. Returns `{"status": "ok"}`. No other functionality. |
| 12 | Test configuration | `pytest.ini` + one passing health check test in `tests/test_health.py` |
| 13 | `.gitignore` | Python-appropriate (`.venv/`, `__pycache__/`, `.env`, `data/*.db`, etc.) |
| 14 | `git init` + initial commit | Repository initialized with all Phase 0 files |

### forge.json

```json
{
  "project_name": "ForgeTrade",
  "backend": {
    "language": "python",
    "entry_module": "app.main",
    "test_framework": "pytest",
    "test_dir": "tests",
    "dependency_file": "requirements.txt",
    "venv_path": ".venv"
  },
  "frontend": {
    "enabled": false,
    "dir": null,
    "build_cmd": null,
    "test_cmd": null
  }
}
```

### Acceptance Criteria

1. `scripts/run_tests.ps1` exits 0 (static checks pass + health test passes).
2. App boots and `GET /health` returns `{"status": "ok"}`.
3. All `Contracts/` files exist and are non-empty.
4. `forge.json` exists and is valid JSON matching the schema.
5. `.env.example` lists all required environment variables from `stack.md`.
6. `db/migrations/001_initial_schema.sql` contains valid SQLite SQL matching `schema.md`.
7. `git log` shows one initial commit.

### Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots, `/health` responds 200 |
| **Behavior** | Health test passes via pytest |
| **Contract** | All Contracts/ files present. Physics declares `/health`. Boundaries.json parseable. |

### Post-Phase 0

After Phase 0 is `AUTHORIZED` and committed:
- **§1 read gate is ACTIVE** for all subsequent phases.
- **Full audit enforcement** (A1–A9) applies.
- The builder MUST read all contract files before beginning Phase 1.

---

## Phase 1 — OANDA Broker Client

### A) Purpose and UX Target

Establish communication with OANDA's v20 REST API. The bot can fetch candle data, query account state, and place/close orders. This is the foundation every subsequent phase depends on.

### B) Current Constraints

Phase 0 scaffold exists. `/health` works. No broker logic yet. OANDA credentials are in `.env.example` but no code reads them.

### C) Scope

#### Constraints
- This phase does NOT implement strategy, risk management, or the trading loop.
- Only `app/broker/` files are created/modified. `app/main.py` updated minimally to load config.

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | `app/broker/oanda_client.py` | Async client wrapping OANDA v20 REST: fetch candles (Daily, 4H), get account summary, place market order with SL/TP, close position, list open positions |
| 2 | `app/broker/models.py` | Dataclasses/typed dicts for Candle, AccountSummary, OrderRequest, OrderResponse, Position |
| 3 | `app/config.py` | Load `.env` variables into a typed config object. Validate required vars on startup. |
| 4 | Tests | Mock OANDA responses, test candle parsing, order construction, error handling |

### D) Non-Goals (Explicitly Out of Scope)

- No trading loop or scheduling
- No strategy evaluation
- No position sizing or risk math

### E) Acceptance Criteria

#### Functional
1. `OandaClient.fetch_candles("EUR_USD", "D", count=50)` returns parsed Candle objects from mock data
2. `OandaClient.get_account_summary()` returns balance, equity, open position count from mock data
3. `OandaClient.place_order(...)` constructs a valid v20 market order payload with SL/TP
4. Config loads all `.env` variables and raises clear errors on missing required vars
5. Practice vs live endpoint is selected based on `OANDA_ENVIRONMENT`

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| `test_parse_candles` | Candle dataclass fields populated correctly from mock JSON |
| `test_account_summary` | Balance and equity parsed from mock response |
| `test_order_payload` | Market order JSON matches OANDA v20 spec (direction, units, SL, TP) |
| `test_config_missing_var` | Raises error with message naming the missing variable |
| `test_environment_switching` | Practice URL for `practice`, live URL for `live` |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots, `/health` responds 200 |
| **Behavior** | All broker client tests pass |
| **Contract** | No boundary violations in `app/broker/` |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| Broker client | `app/broker/oanda_client.py` | `OandaClient` class |
| Config loader | `app/config.py` | `load_config()` |

---

## Phase 2 — Strategy Engine

### A) Purpose and UX Target

Implement the core trading strategy: S/R zone detection from Daily candles and entry signal evaluation from 4H candles. All pure functions — given candles, return zones and signals.

### B) Current Constraints

Broker client (Phase 1) can fetch candles. No strategy module exists yet. No trading loop.

### C) Scope

#### Constraints
- Only `app/strategy/` files are created/modified.
- Strategy functions take candle arrays as input, return zones/signals as output. No I/O.

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | `app/strategy/sr_zones.py` | Detect swing highs/lows from Daily candles (50 lookback). Cluster into horizontal support/resistance zones. |
| 2 | `app/strategy/signals.py` | Given 4H candles and S/R zones: detect price touching a zone, evaluate rejection wick (wick > 50% of body), determine direction (buy at support, sell at resistance). Return entry signal or None. |
| 3 | `app/strategy/session_filter.py` | Check if current UTC time is within London+NY session (07:00–21:00 UTC). Pure function. |
| 4 | `app/strategy/indicators.py` | ATR(14) calculation from candle data. |
| 5 | `app/strategy/models.py` | Dataclasses: SRZone, EntrySignal, CandleData |
| 6 | Tests | Deterministic tests with known candle fixtures. Same input = same output, always. |

### D) Non-Goals (Explicitly Out of Scope)

- No broker calls from strategy
- No trading loop
- No position sizing (that's risk manager, Phase 3)

### E) Acceptance Criteria

#### Functional
1. Given 50 Daily candles with known swing highs/lows, `detect_sr_zones()` returns correct zone levels
2. Given 4H candles where price touches support and closes with a rejection wick, `evaluate_signal()` returns a buy signal
3. Given 4H candles where price touches resistance and closes with a rejection wick, `evaluate_signal()` returns a sell signal
4. Given 4H candles with no zone touch, `evaluate_signal()` returns None
5. Session filter returns True at 12:00 UTC and False at 03:00 UTC
6. ATR(14) calculation matches known expected values

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| `test_sr_zone_detection` | Correct support/resistance levels from fixture candles |
| `test_rejection_wick_buy` | Buy signal at support with valid rejection wick |
| `test_rejection_wick_sell` | Sell signal at resistance with valid rejection wick |
| `test_no_signal_no_touch` | None when price doesn't touch any zone |
| `test_no_signal_no_wick` | None when price touches zone but no rejection wick |
| `test_session_filter_in` | True during London/NY overlap |
| `test_session_filter_out` | False during Asian session |
| `test_atr_calculation` | ATR(14) matches hand-calculated value |
| `test_determinism` | Two calls with same candles produce identical output |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots, `/health` responds 200 |
| **Behavior** | All strategy tests pass |
| **Contract** | No boundary violations in `app/strategy/` (no I/O imports) |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| S/R detection | `app/strategy/sr_zones.py` | `detect_sr_zones()` |
| Signal evaluation | `app/strategy/signals.py` | `evaluate_signal()` |
| Session filter | `app/strategy/session_filter.py` | `is_in_session()` |
| ATR | `app/strategy/indicators.py` | `calculate_atr()` |

---

## Phase 3 — Risk Manager + Order Execution

### A) Purpose and UX Target

Position sizing (1% risk), SL/TP calculation, drawdown tracking, and the circuit breaker. Plus the orchestration that connects strategy signals to broker orders.

### B) Current Constraints

Broker client (Phase 1) handles OANDA API. Strategy (Phase 2) produces signals. No risk math or trade execution yet.

### C) Scope

#### Constraints
- `app/risk/` for risk math (pure, no I/O)
- `app/engine.py` for the orchestration loop (connects strategy → risk → broker → repos)

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | `app/risk/position_sizer.py` | Calculate units from account equity, risk %, SL distance, and pip value |
| 2 | `app/risk/sl_tp.py` | Calculate SL (1.5× ATR beyond S/R zone) and TP (next zone or 1:2 RR) |
| 3 | `app/risk/drawdown.py` | Track peak equity, calculate current drawdown %, trigger circuit breaker at 10% |
| 4 | `app/engine.py` | Trading loop: fetch candles → evaluate signal → check risk → place order → log trade. Runs on a polling interval. |
| 5 | Tests | Position sizing math, SL/TP calculation, drawdown scenarios, circuit breaker activation |

### D) Non-Goals (Explicitly Out of Scope)

- No backtest engine (Phase 5)
- No CLI dashboard output (Phase 4)

### E) Acceptance Criteria

#### Functional
1. Position sizing: $10,000 equity, 1% risk, 30 pip SL → correct unit count
2. SL placed at 1.5× ATR(14) beyond the S/R zone in the correct direction
3. TP placed at next S/R zone or 1:2 RR, whichever is closer to entry
4. Circuit breaker activates when drawdown exceeds 10% from peak
5. Trading loop polls, evaluates, and can place a mock order end-to-end

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| `test_position_sizing` | Correct units for given equity, risk %, SL distance |
| `test_sl_calculation_buy` | SL = zone_price - (1.5 × ATR) for buy trades |
| `test_sl_calculation_sell` | SL = zone_price + (1.5 × ATR) for sell trades |
| `test_tp_next_zone` | TP = next zone when closer than 1:2 RR |
| `test_tp_rr_ratio` | TP = 1:2 RR when next zone is farther |
| `test_drawdown_tracking` | Drawdown % correct after equity decline |
| `test_circuit_breaker_fires` | Trading halted when drawdown > 10% |
| `test_circuit_breaker_not_fires` | Trading continues when drawdown < 10% |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots, `/health` responds 200 |
| **Behavior** | All risk + engine tests pass |
| **Contract** | No boundary violations across all layers |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| Position sizer | `app/risk/position_sizer.py` | `calculate_units()` |
| SL/TP calculator | `app/risk/sl_tp.py` | `calculate_sl()`, `calculate_tp()` |
| Drawdown tracker | `app/risk/drawdown.py` | `DrawdownTracker` class |
| Trading engine | `app/engine.py` | `TradingEngine` class |

---

## Phase 4 — Trade Logging + CLI Dashboard

### A) Purpose and UX Target

Persist every trade to SQLite. Display bot status, open positions, equity, and daily P&L in the PowerShell console. Wire up the `/status` and `/trades` internal API endpoints.

### B) Current Constraints

Engine (Phase 3) can execute trades. No persistence or console output yet. SQLite migration exists but hasn't been executed.

### C) Scope

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | `app/repos/trade_repo.py` | SQLite CRUD: insert trade, update trade (close), query trades by status/date |
| 2 | `app/repos/equity_repo.py` | Insert equity snapshots, query latest, query history for drawdown |
| 3 | `app/repos/db.py` | DB initialization: run migrations on first boot, connection management |
| 4 | `app/cli/dashboard.py` | Periodic console output: format and print bot status table to stdout |
| 5 | `app/api/routers.py` | Wire up `GET /status` and `GET /trades` per `physics.yaml` |
| 6 | Tests | Repo tests with in-memory SQLite, dashboard output tests, API endpoint tests |

### D) Non-Goals (Explicitly Out of Scope)

- No backtest engine (Phase 5)
- No rich TUI framework (plain print statements are fine)

### E) Acceptance Criteria

#### Functional
1. Trades are persisted to SQLite on entry and updated on exit
2. Equity snapshots recorded every polling cycle
3. Console prints status line showing: mode, equity, P&L, open positions, drawdown %
4. `GET /status` returns current bot state as JSON
5. `GET /trades` returns recent trades as JSON
6. DB is auto-initialized on first boot (migrations run if tables don't exist)

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| `test_insert_trade` | Trade row created in SQLite |
| `test_close_trade` | Trade row updated with exit price, P&L, closed_at |
| `test_equity_snapshot` | Snapshot row created with correct values |
| `test_status_endpoint` | `/status` returns 200 with expected schema |
| `test_trades_endpoint` | `/trades` returns 200 with trade list |
| `test_db_init_idempotent` | Running init twice doesn't error or duplicate tables |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots, `/health` and `/status` respond 200 |
| **Behavior** | All repo + API tests pass |
| **Contract** | No boundary violations. `/status` and `/trades` match physics.yaml. |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| Trade repo | `app/repos/trade_repo.py` | `TradeRepo` class |
| Equity repo | `app/repos/equity_repo.py` | `EquityRepo` class |
| DB init | `app/repos/db.py` | `init_db()` |
| Dashboard | `app/cli/dashboard.py` | `print_status()` |
| API routes | `app/api/routers.py` | `router` |

---

## Phase 5 — Backtest Engine

### A) Purpose and UX Target

Replay historical candle data through the strategy and risk engine. Produce summary stats (win rate, profit factor, Sharpe ratio, max drawdown). Output to console and store results in SQLite.

### B) Current Constraints

Strategy, risk manager, trade logging all functional. Broker client can fetch historical candles. No backtest-specific code yet.

### C) Scope

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | `app/backtest/engine.py` | Iterate historical candles chronologically. Feed into strategy → risk → simulated execution. Track virtual equity. |
| 2 | `app/backtest/stats.py` | Calculate win rate, profit factor, Sharpe ratio, max drawdown from completed backtest trades |
| 3 | `app/repos/backtest_repo.py` | Persist backtest run summary to `backtest_runs` table |
| 4 | CLI command | `python -m app.main --mode backtest --start 2024-01-01 --end 2025-01-01` |
| 5 | Tests | Backtest with known candle data produces expected trade count and stats |

### D) Non-Goals (Explicitly Out of Scope)

- No strategy parameter optimization
- No chart visualization
- No Monte Carlo simulation

### E) Acceptance Criteria

#### Functional
1. Backtest engine replays 1 year of Daily+4H candles and produces trades
2. Stats calculation correct: win rate = winners/total, profit factor = gross profit/gross loss
3. Backtest trades logged to `trades` table with `mode='backtest'`
4. Summary logged to `backtest_runs` table
5. Console prints summary at completion

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| `test_backtest_known_data` | Known candle fixture produces expected trade count |
| `test_stats_calculation` | Win rate, profit factor correct for known trade set |
| `test_sharpe_ratio` | Sharpe correct for known returns series |
| `test_backtest_persisted` | Backtest run row exists in SQLite after completion |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots with `--mode backtest` and runs to completion with fixture data |
| **Behavior** | All backtest tests pass |
| **Contract** | No boundary violations |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| Backtest engine | `app/backtest/engine.py` | `BacktestEngine` class |
| Stats calculator | `app/backtest/stats.py` | `calculate_stats()` |
| Backtest repo | `app/repos/backtest_repo.py` | `BacktestRepo` class |

---

## Phase 6 — Paper & Live Integration

### A) Purpose and UX Target

End-to-end integration: the bot runs against a real OANDA practice account with real market data, or a live account. Config-driven mode switching with safety checks.

### B) Current Constraints

All components functional in isolation and tested with mocks. Not yet tested against real OANDA endpoints.

### C) Scope

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | Integration wiring | Connect engine loop to real broker client (practice API). Polling interval configurable. |
| 2 | Live mode safety | Prominent warning on live boot, 5-second delay per manifesto §6. Separate `.env` validation for live credentials. |
| 3 | Graceful shutdown | Handle Ctrl+C: close open positions (optional, configurable), flush logs, exit cleanly. |
| 4 | Error resilience | Retry on OANDA API errors, skip cycle on bad data, log all failures. |
| 5 | Integration tests | Paper mode connects, fetches candles, evaluates strategy (does not require placing trades). |

### D) Non-Goals (Explicitly Out of Scope)

- No multi-pair support
- No remote deployment
- No notifications

### E) Acceptance Criteria

#### Functional
1. Bot starts in paper mode, connects to OANDA practice API, fetches candles, begins evaluation loop
2. Bot starts in live mode, prints warning, waits 5 seconds, then enters loop
3. Ctrl+C triggers graceful shutdown: logs final state, exits with code 0
4. OANDA API timeout → bot skips cycle, logs error, retries next interval
5. All trades placed via paper mode appear in OANDA practice account history

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| `test_live_mode_warning` | Warning message logged when mode=live |
| `test_graceful_shutdown` | Shutdown handler flushes DB and exits cleanly |
| `test_api_error_retry` | Bot continues after transient OANDA error |
| `test_paper_live_same_logic` | Same candle data produces same signal regardless of mode |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots in paper mode without crashing (may not place trades if market is closed) |
| **Behavior** | All integration tests pass |
| **Contract** | No boundary violations. All physics endpoints respond correctly. |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| Engine wiring | `app/engine.py` | `TradingEngine.run()` |
| Live safety | `app/main.py` | startup sequence |
| Shutdown handler | `app/main.py` | signal handler |
