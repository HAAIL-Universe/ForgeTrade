# ForgeTrade — Build Phases

This document defines the phased build plan. Each phase is a self-contained unit of work with clear acceptance criteria, verification gates, and scope boundaries.

The builder executes one phase at a time. Each phase must pass the full verification hierarchy (static → runtime → behavior → contract) and the audit script before sign-off.

---

## Completed Phases (Summary)

Phases 0–6 are **COMPLETE** and committed. The codebase as of 2026-02-16 contains:

| Phase | Name | Status |
|-------|------|--------|
| 0 | Genesis (Bootstrap) | ✅ Complete |
| 1 | OANDA Broker Client | ✅ Complete |
| 2 | Strategy Engine (S/R + Rejection Wicks) | ✅ Complete |
| 3 | Risk Manager + Order Execution | ✅ Complete |
| 4 | Trade Logging + CLI Dashboard | ✅ Complete |
| 5 | Backtest Engine | ✅ Complete |
| 6 | Paper & Live Integration | ✅ Complete |

### Current Architecture Snapshot

```
app/
  main.py              ← FastAPI app + CLI entry, boots engine
  config.py            ← .env → typed Config dataclass
  engine.py            ← TradingEngine: poll loop, single-pair, D+H4 S/R strategy
  api/routers.py       ← GET /status, GET /trades (shared mutable state)
  broker/
    oanda_client.py    ← Async OANDA v20 REST client (with retry + backoff)
    models.py          ← Candle, AccountSummary, OrderRequest, OrderResponse, Position
  strategy/
    sr_zones.py        ← Swing-high/low clustering → SRZone list
    signals.py         ← Rejection-wick detection at S/R zones → EntrySignal
    indicators.py      ← ATR(14)
    session_filter.py  ← UTC hour range check
    models.py          ← CandleData, SRZone, EntrySignal
  risk/
    position_sizer.py  ← Units from equity, risk %, SL distance
    sl_tp.py           ← SL = 1.5×ATR beyond zone, TP = next zone or 1:2 RR
    drawdown.py        ← DrawdownTracker + circuit breaker at 10%
  repos/
    db.py              ← SQLite init + connection factory
    trade_repo.py      ← trades table CRUD
    equity_repo.py     ← equity_snapshots table CRUD
    backtest_repo.py   ← backtest_runs table CRUD
  backtest/
    engine.py          ← Replays Daily+4H candles through strategy
    stats.py           ← Win rate, profit factor, Sharpe, max drawdown
  cli/dashboard.py     ← Console status line printer
```

### Current Limitations (Addressed by Phases 7–10)

1. **No web dashboard** — status is only visible via console print or raw API JSON.
2. **Single-stream only** — one `TradingEngine`, one pair (`EUR_USD`), one strategy (S/R swing), one set of timeframes (`D` + `H4`).
3. **No watchlist concept** — signals that don't result in orders are discarded silently.
4. **Engine is hardcoded to S/R rejection** — `run_once()` contains the full strategy pipeline inline; no plugin/strategy abstraction.
5. **Config is single-pair** — `Config` has one `trade_pair`, no concept of multiple streams.
6. **No EMA or trend-following indicators** — only ATR exists.
7. **Position sizing assumes EUR/USD pip value** — `pip_value=0.0001` default won't work for XAU_USD.

---

## Phase 7 — Web Dashboard

### A) Purpose and UX Target

A single-page dark-themed web dashboard served directly by FastAPI. Displays real-time bot state: account metrics, open positions, pending signals (watchlist), closed trades with P&L, and per-stream status. No build tools, no npm, no framework — one HTML file with vanilla JS polling the API.

The dashboard answers every question a trader asks when glancing at their screen:
- Is the bot running? What mode?
- What's my equity and drawdown right now?
- Any open positions? What are their SL/TP levels?
- Is it watching anything it might enter soon?
- What did it close today and how much did I make/lose?

### B) Current Constraints

- `GET /status` exists but returns limited fields from a mutable dict in `routers.py`.
- `GET /trades` exists and queries SQLite via `TradeRepo`.
- `OandaClient.list_open_positions()` exists but is not exposed via any API endpoint.
- No concept of a "pending signal" — `run_once()` evaluates and either enters or discards.
- `app/static/` directory does not exist.
- `forge.json` has `"frontend": {"enabled": false}`.

### C) Scope

#### Constraints
- NO JavaScript framework, NO npm, NO build step. One HTML file with inline CSS and vanilla JS.
- NO changes to trading logic or the engine loop.
- API additions are read-only — no new write endpoints.
- Dashboard polls via `fetch()` on an interval; no WebSockets in this phase.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Positions endpoint** | `app/api/routers.py` | Add `GET /positions` — calls `OandaClient.list_open_positions()` and returns the list. Requires broker instance injected into routers. |
| 2 | **Watchlist state** | `app/engine.py`, `app/api/routers.py` | After `evaluate_signal()`, store the result (even when None or when an order is NOT placed due to circuit breaker / existing position) in shared state as `last_signal`. Add `GET /signals/pending` endpoint that returns the last evaluated signal with its timestamp and status (`watching`, `entered`, `no_signal`, `skipped`). |
| 3 | **Closed trades endpoint** | `app/api/routers.py` | Add `GET /trades/closed` — delegates to `TradeRepo.get_trades(status_filter="closed")` with `limit` param. Response includes P&L per trade and a running total. |
| 4 | **Enrich /status** | `app/api/routers.py`, `app/engine.py` | Add fields to `_bot_status`: `stream_name`, `cycle_count`, `last_cycle_at`, `last_signal_time`, `last_order_time`. Engine updates these each cycle. |
| 5 | **Static file serving** | `app/main.py` | Mount `app/static/` via `app.mount("/dashboard", StaticFiles(directory="app/static"), name="dashboard")`. Add redirect from `/` to `/dashboard/index.html`. |
| 6 | **Dashboard HTML** | `app/static/index.html` | Single file. Sections: Header (mode badge, uptime), Account bar (equity, balance, drawdown, circuit breaker), Open Positions table, Watchlist panel, Closed Trades table (with P&L colour), Stream Status table (for Phase 9 readiness). Polls every 5 seconds. |
| 7 | **Update forge.json** | `forge.json` | Set `"frontend": {"enabled": true, "dir": "app/static", "build_cmd": null, "test_cmd": null}`. |
| 8 | **Tests** | `tests/test_dashboard_api.py` | Test new endpoints return correct schemas. Test static mount serves HTML. |

#### Dashboard Layout Specification

```
┌──────────────────────────────────────────────────────────────────┐
│  FORGETRADE                                    ● PAPER │ ▲ 4h32m│
├───────────────┬───────────────┬──────────────┬───────────────────┤
│  EQUITY       │  BALANCE      │  DRAWDOWN    │  CIRCUIT BREAKER  │
│  $10,245.30   │  $10,000.00   │  2.45%       │  ● OFF            │
│  ▲ +$245.30   │               │  ██░░░░░ 10% │                   │
├───────────────┴───────────────┴──────────────┴───────────────────┤
│                                                                  │
│  OPEN POSITIONS                                         0 open   │
│  ┌────────┬──────┬────────┬─────────┬─────────┬─────────┬──────┐│
│  │ Pair   │ Dir  │ Units  │ Entry   │ SL      │ TP      │ uP&L ││
│  │ —      │ —    │ —      │ —       │ —       │ —       │ —    ││
│  └────────┴──────┴────────┴─────────┴─────────┴─────────┴──────┘│
│                                                                  │
│  WATCHLIST                                                       │
│  ┌────────┬──────┬──────────┬──────────────────────────────────┐ │
│  │ Pair   │ Dir  │ Zone     │ Reason                          │ │
│  │ EUR/USD│ BUY  │ 1.08200  │ Rejection wick at support       │ │
│  └────────┴──────┴──────────┴──────────────────────────────────┘ │
│                                                                  │
│  CLOSED TRADES (today)                          Total: +$127.40  │
│  ┌────────┬──────┬─────────┬─────────┬─────────┬──────┬────────┐│
│  │ Pair   │ Dir  │ Entry   │ Exit    │ P&L     │ Pips │ Time   ││
│  │ EUR/USD│ SELL │ 1.09120 │ 1.08900 │ +$23.40 │ +22  │ 14:32  ││
│  │ EUR/USD│ BUY  │ 1.08450 │ 1.08310 │ -$14.20 │ -14  │ 11:07  ││
│  └────────┴──────┴─────────┴─────────┴─────────┴──────┴────────┘│
│                                                                  │
│  STREAMS                                                         │
│  ┌────────────────┬─────────┬────────┬──────────┬──────────────┐ │
│  │ Name           │ Pair    │ Cycle  │ Status   │ Last Signal  │ │
│  │ sr-swing       │ EUR/USD │ 142    │ ● active │ 2 cycles ago │ │
│  │ micro-scalp    │ XAU/USD │ —      │ ○ off    │ —            │ │
│  └────────────────┴─────────┴────────┴──────────┴──────────────┘ │
│                                                                  │
│  Last refresh: 14:35:02 UTC          Polling: every 5s           │
└──────────────────────────────────────────────────────────────────┘
```

#### Colour Rules
- Equity change: green if positive, red if negative.
- P&L column: green text for profit, red text for loss.
- Drawdown bar: yellow 0–5%, orange 5–8%, red 8%+.
- Circuit breaker badge: green "OFF", pulsing red "ACTIVE".
- Mode badge: blue "PAPER", red "LIVE" with glow, purple "BACKTEST".
- Stream status dot: green = active, grey = off, red = error.

#### CSS Theme
- Background: `#0d1117` (GitHub dark).
- Card surfaces: `#161b22`.
- Text: `#c9d1d9`.
- Borders: `#30363d`.
- Font: `"JetBrains Mono", "Fira Code", monospace` for numbers, system sans-serif for labels.

### D) Non-Goals (Explicitly Out of Scope)

- No WebSocket live-streaming (polling is sufficient at 5s intervals).
- No user authentication (internal dashboard, local network only).
- No trade placement from the dashboard (read-only).
- No chart rendering or candlestick visualization.
- No React/Vue/Svelte or any JS framework.

### E) Acceptance Criteria

#### Functional
1. Navigating to `http://localhost:8080/dashboard/` renders the full dashboard.
2. Dashboard auto-refreshes every 5 seconds without page reload.
3. `GET /positions` returns current open positions with unrealized P&L.
4. `GET /signals/pending` returns the last evaluated signal object or null.
5. `GET /trades/closed?limit=20` returns closed trades with P&L fields.
6. `GET /status` includes `stream_name`, `cycle_count`, `last_cycle_at`.
7. All numbers in the dashboard use monospace font and proper formatting ($, %, pips).
8. P&L values are coloured green (positive) or red (negative).
9. Dashboard renders correctly with zero open positions and zero trades (empty state).
10. Page loads in under 200ms (no external CDN dependencies, everything inline).

#### Unit Tests

| Test case | File | Asserts |
|-----------|------|---------|
| `test_positions_endpoint` | `tests/test_dashboard_api.py` | `/positions` returns 200 with list schema |
| `test_pending_signals_endpoint` | `tests/test_dashboard_api.py` | `/signals/pending` returns 200, shape matches `EntrySignal` or null |
| `test_closed_trades_endpoint` | `tests/test_dashboard_api.py` | `/trades/closed` returns only closed trades with pnl field |
| `test_status_enriched` | `tests/test_dashboard_api.py` | `/status` includes `cycle_count` and `last_cycle_at` |
| `test_dashboard_served` | `tests/test_dashboard_api.py` | `GET /dashboard/index.html` returns 200 with `text/html` |
| `test_root_redirect` | `tests/test_dashboard_api.py` | `GET /` redirects to `/dashboard/index.html` |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots, `/health` responds 200, `/dashboard/` renders HTML |
| **Behavior** | All dashboard API tests pass |
| **Contract** | New endpoints return schemas consistent with existing models |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | What Changes |
|-----------|------|-------------|
| Positions endpoint | `app/api/routers.py` | Add `GET /positions`, inject broker reference |
| Pending signals | `app/engine.py` | Store `last_signal` in shared state after `evaluate_signal()` |
| Signals endpoint | `app/api/routers.py` | Add `GET /signals/pending`, read from shared state |
| Closed trades | `app/api/routers.py` | Add `GET /trades/closed` (thin wrapper around existing repo) |
| Status enrichment | `app/engine.py` → `app/api/routers.py` | Engine calls `update_bot_status()` with cycle count, timestamps |
| Static mount | `app/main.py` | `StaticFiles` mount + root redirect |
| Dashboard | `app/static/index.html` | New file, ~400 lines HTML/CSS/JS |
| Config | `forge.json` | `frontend.enabled = true` |

### H) Dependency Changes

- Add `aiofiles` to `requirements.txt` (required by `StaticFiles` in FastAPI).
- No other new dependencies.

---

## Phase 8 — Strategy Abstraction + EMA Indicators

### A) Purpose and UX Target

Refactor the engine so strategies are pluggable. Extract the current S/R rejection-wick logic into a named strategy class. Add EMA (Exponential Moving Average) to the indicator library. This phase creates the foundation for running different strategies on different streams without duplicating the engine.

After this phase, adding a new strategy means writing one class that implements a known interface — no changes to the engine, risk, or broker layers.

### B) Current Constraints

- `TradingEngine.run_once()` contains the full strategy pipeline inline (fetch D candles → detect zones → fetch H4 → evaluate signal → calculate SL/TP → place order). All 7 steps are hardcoded.
- There is no strategy interface or base class.
- Only ATR exists in `indicators.py`. No EMA.
- `Config` has a single `trade_pair` field.
- `position_sizer.calculate_units()` defaults to `pip_value=0.0001` (EUR/USD only).

### C) Scope

#### Constraints
- Engine refactor is internal — the external behavior (same trades, same timing) must not change.
- The existing S/R strategy must produce **identical** signals before and after refactoring.
- No new trading mode or second stream yet (that's Phase 9).

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Strategy protocol** | `app/strategy/base.py` | Define `StrategyProtocol` (Python `Protocol` class) with methods: `async def evaluate(self, broker, config) -> StrategyResult \| None`. `StrategyResult` is a new dataclass holding: `signal: EntrySignal`, `sl: float`, `tp: float`, `atr: float`. This bundles signal + risk into one output so the engine doesn't need to know which indicator or zone method was used. |
| 2 | **S/R rejection strategy class** | `app/strategy/sr_rejection.py` | Extract the current inline logic from `TradingEngine.run_once()` steps 3–5 into `SRRejectionStrategy` implementing `StrategyProtocol`. Internally calls `fetch_candles(D)`, `detect_sr_zones()`, `fetch_candles(H4)`, `evaluate_signal()`, `calculate_atr()`, `calculate_sl()`, `calculate_tp()`. Returns `StrategyResult` or `None`. |
| 3 | **Refactor engine** | `app/engine.py` | `TradingEngine.__init__()` accepts a `strategy: StrategyProtocol` parameter. `run_once()` calls `strategy.evaluate(broker, config)` and then handles position sizing + order placement with the returned `StrategyResult`. Steps 1 (circuit breaker), 2 (session filter), 6 (account/sizing), 7 (order) remain in the engine. Steps 3-5 (fetch + signal + SL/TP) move into the strategy. |
| 4 | **EMA indicator** | `app/strategy/indicators.py` | Add `calculate_ema(candles, period) -> list[float]`. Standard EMA formula: `EMA_today = close × k + EMA_yesterday × (1 - k)` where `k = 2 / (period + 1)`. Returns the full EMA series so the caller can check crossovers and slopes. |
| 5 | **Pip value config** | `app/strategy/models.py`, `app/config.py` | Add instrument metadata: `pip_value` per instrument. EUR_USD = 0.0001, XAU_USD = 0.01. The engine passes this to `calculate_units()` instead of using the hardcoded default. Add `INSTRUMENT_PIP_VALUES` dict to models. |
| 6 | **Update main.py** | `app/main.py` | Construct `SRRejectionStrategy()` and pass it to `TradingEngine(config, broker, strategy)`. |
| 7 | **Update backtest engine** | `app/backtest/engine.py` | Accept a `strategy` parameter. For now, default to `SRRejectionStrategy` with an offline/mock broker adapter so it can call `strategy.evaluate()` in the same pattern. *(Minimal change — backtest can also remain using direct function calls internally for now, with a TODO for full strategy-protocol backtest support.)* |
| 8 | **Determinism tests** | `tests/test_strategy_abstraction.py` | Verify that the refactored `SRRejectionStrategy` produces the exact same signals as the old inline code given identical candle fixtures. This is the critical regression gate. |
| 9 | **EMA tests** | `tests/test_strategy.py` | EMA calculation matches hand-computed values. EMA(21), EMA(50) crossover detection works correctly. |

### D) Non-Goals (Explicitly Out of Scope)

- No trend-scalp strategy implementation yet (Phase 10).
- No multi-stream engine (Phase 9).
- No change to what trades the bot actually makes — this is a pure refactor.

### E) Acceptance Criteria

#### Functional
1. `SRRejectionStrategy.evaluate()` returns the same `StrategyResult` as the old inline `run_once()` logic for identical candle data.
2. `calculate_ema([candles], 21)` returns correct EMA values matching hand computation.
3. `calculate_ema([candles], 50)` returns correct EMA values.
4. `INSTRUMENT_PIP_VALUES["EUR_USD"]` == `0.0001`, `INSTRUMENT_PIP_VALUES["XAU_USD"]` == `0.01`.
5. `TradingEngine` can be instantiated with any object satisfying `StrategyProtocol`.
6. All existing tests continue to pass unchanged (or with minimal fixture adjustments for the new constructor signature).

#### Unit Tests

| Test case | File | Asserts |
|-----------|------|---------|
| `test_sr_strategy_matches_old_logic` | `tests/test_strategy_abstraction.py` | Given identical candle fixture, new strategy class returns same signal direction, entry, SL, TP as old inline code |
| `test_sr_strategy_no_signal` | `tests/test_strategy_abstraction.py` | Returns None when old logic would return `{"action": "skipped"}` |
| `test_strategy_protocol_duck_type` | `tests/test_strategy_abstraction.py` | A mock strategy implementing the protocol can be passed to `TradingEngine` |
| `test_ema_known_values` | `tests/test_strategy.py` | EMA(21) of a known price series matches expected output (tolerance 1e-6) |
| `test_ema_crossover` | `tests/test_strategy.py` | EMA(21) crossing above EMA(50) is detectable from the returned series |
| `test_pip_value_eur_usd` | `tests/test_strategy.py` | Correct pip value for EUR_USD |
| `test_pip_value_xau_usd` | `tests/test_strategy.py` | Correct pip value for XAU_USD |
| `test_engine_uses_strategy` | `tests/test_engine.py` | Engine calls `strategy.evaluate()` and uses the returned SL/TP values |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots in paper mode, runs at least one cycle with `SRRejectionStrategy` |
| **Behavior** | All strategy abstraction tests + EMA tests pass |
| **Contract** | `StrategyProtocol` is importable. `SRRejectionStrategy` satisfies it. No boundary violations. |
| **Regression** | **ALL** existing tests pass unchanged (critical — this is a refactor, not a feature) |

### G) Implementation Entrypoint Notes

| Component | File | What Changes |
|-----------|------|-------------|
| Strategy protocol | `app/strategy/base.py` | New file |
| S/R strategy class | `app/strategy/sr_rejection.py` | New file (extracts from `engine.py` steps 3-5) |
| Engine refactor | `app/engine.py` | `__init__` gains `strategy` param; `run_once()` simplified |
| EMA indicator | `app/strategy/indicators.py` | Add `calculate_ema()` |
| Pip values | `app/strategy/models.py` | Add `INSTRUMENT_PIP_VALUES` dict |
| Config | `app/config.py` | No changes needed (pip value looked up from instrument name) |
| Main wiring | `app/main.py` | Construct strategy, pass to engine |
| Backtest | `app/backtest/engine.py` | Accept optional strategy param |
| Tests | `tests/test_strategy_abstraction.py` | New file |
| Tests | `tests/test_strategy.py` | Add EMA test cases |

### H) Dependency Changes

None.

---

## Phase 9 — Multi-Stream Engine Manager

### A) Purpose and UX Target

Run multiple `TradingEngine` instances concurrently, each with its own instrument, strategy, timeframes, and polling interval. A single OANDA account drives both streams. The operator configures streams declaratively in `forge.json` and toggles them on/off without code changes.

After this phase:
- `boot.ps1` starts **all enabled streams** simultaneously.
- The dashboard shows per-stream status (cycle count, last signal, active/off).
- Each stream has independent drawdown tracking but shares a global account equity check.

### B) Current Constraints

- `TradingEngine` accepts one `Config` (which has one `trade_pair`).
- `_run_cli()` creates one `TradingEngine` and calls `engine.run()`.
- `OandaClient` is stateless per-request (safe to share across streams).
- `DrawdownTracker` is per-engine instance (already isolated — good).
- `routers.py` has a single `_bot_status` dict.
- Dashboard (Phase 7) has a Streams table ready to display multiple rows.

### C) Scope

#### Constraints
- No new strategy logic — this phase only builds the multi-stream orchestrator.
- Each stream is a separate `TradingEngine` with its own polling loop.
- Streams run as concurrent `asyncio` tasks (NOT threads or processes).
- The OANDA rate limit is 120 requests/second — with two streams polling at 5s and 300s, we're well within limits.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **StreamConfig dataclass** | `app/models/stream_config.py` | `StreamConfig(name, instrument, strategy_type, timeframes, poll_interval, risk_per_trade_pct, max_concurrent_positions, session_start_utc, session_end_utc, enabled)`. Immutable dataclass. |
| 2 | **Load streams from forge.json** | `app/config.py` | Add a `streams` array to `forge.json`. `load_config()` returns both the global `Config` and a `list[StreamConfig]`. If no `streams` array exists, synthesize one default stream from the existing `Config` fields for backward compatibility. |
| 3 | **EngineManager** | `app/engine_manager.py` | New class. Takes `Config`, `OandaClient`, and `list[StreamConfig]`. For each enabled stream, creates a `TradingEngine` with the appropriate strategy (looked up by `strategy_type` from a registry). Runs all engines via `asyncio.gather()`. Aggregates status from all engines. Handles shutdown (stops all engines on signal). |
| 4 | **Per-stream TradingEngine config** | `app/engine.py` | `TradingEngine.__init__()` accepts `StreamConfig` instead of relying on global `Config` for instrument-specific fields (pair, risk %, session hours, poll interval). Global `Config` still used for OANDA credentials, DB path, etc. |
| 5 | **Per-stream status** | `app/api/routers.py` | Change `_bot_status` from a single dict to a dict-of-dicts keyed by stream name. `GET /status` returns all streams. Add `GET /status/{stream_name}` for a single stream. Dashboard polls `/status` and renders one row per stream in the Streams table. |
| 6 | **Per-stream trade tagging** | `app/repos/trade_repo.py`, DB migration | Add `stream_name TEXT` column to the `trades` table. New migration `002_add_stream_name.sql`. `GET /trades` accepts optional `?stream=` filter. |
| 7 | **Updated main.py** | `app/main.py` | Replace single `TradingEngine` creation with `EngineManager`. Pass it to `asyncio.run()`. Wire up shutdown signal to stop all streams. |
| 8 | **Updated boot.ps1** | `scripts/boot.ps1` | No changes needed — it already calls `python -m app.main --mode paper`. The engine manager handles multiple streams internally. |
| 9 | **forge.json streams config** | `forge.json` | Add `streams` array. Initial config: one enabled stream (`sr-swing`, EUR_USD) and one disabled placeholder (`micro-scalp`, XAU_USD). |

#### forge.json Streams Schema

```json
{
  "project_name": "ForgeTrade",
  "backend": { "..." : "..." },
  "frontend": { "..." : "..." },
  "streams": [
    {
      "name": "sr-swing",
      "instrument": "EUR_USD",
      "strategy": "sr_rejection",
      "timeframes": ["D", "H4"],
      "poll_interval_seconds": 300,
      "risk_per_trade_pct": 1.0,
      "max_concurrent_positions": 1,
      "session_start_utc": 7,
      "session_end_utc": 21,
      "enabled": true
    },
    {
      "name": "micro-scalp",
      "instrument": "XAU_USD",
      "strategy": "trend_scalp",
      "timeframes": ["H1", "M1", "S5"],
      "poll_interval_seconds": 5,
      "risk_per_trade_pct": 0.25,
      "max_concurrent_positions": 3,
      "session_start_utc": 7,
      "session_end_utc": 16,
      "enabled": false
    }
  ]
}
```

#### Concurrency Model

```
main.py
  └─ EngineManager.run()
       └─ asyncio.gather(
            stream_sr_swing.run(),     # polls every 300s
            stream_micro_scalp.run(),  # polls every 5s
          )

Each stream's run() loop:
  while running:
    result = await engine.run_once()
    update_stream_status(stream_name, result)
    await interruptible_sleep(poll_interval)
```

Both streams share:
- One `OandaClient` instance (stateless, safe for concurrent use)
- One SQLite database (writes are serialized by SQLite's built-in locking)
- One FastAPI app (serves all streams' data)

Each stream owns:
- Its own `TradingEngine` instance
- Its own `DrawdownTracker`
- Its own `StrategyProtocol` implementation
- Its own cycle counter and status

### D) Non-Goals (Explicitly Out of Scope)

- No trend-scalp strategy implementation (Phase 10).
- No per-stream separate drawdown limits (both use the global `max_drawdown_pct` for now).
- No auto-discovery of instruments.
- No dynamic stream creation at runtime (requires restart to add/remove streams).

### E) Acceptance Criteria

#### Functional
1. With one stream enabled, behavior is identical to current single-engine mode.
2. With two streams enabled, both run concurrently and log independently.
3. `GET /status` returns a dict with one entry per enabled stream.
4. `GET /trades?stream=sr-swing` returns only trades from that stream.
5. Dashboard Streams table shows one row per stream with correct cycle count.
6. Shutdown signal (`Ctrl+C`) stops all streams gracefully.
7. A disabled stream does not start, does not consume API calls, does not appear in active status.
8. Backward compatibility: if `forge.json` has no `streams` array, a single default stream is synthesized from existing `Config` fields.

#### Unit Tests

| Test case | File | Asserts |
|-----------|------|---------|
| `test_single_stream_backward_compat` | `tests/test_engine_manager.py` | No `streams` config → one default stream created matching old behavior |
| `test_two_streams_concurrent` | `tests/test_engine_manager.py` | Two mock engines both called `.run()` via `asyncio.gather`, both complete |
| `test_disabled_stream_skipped` | `tests/test_engine_manager.py` | Stream with `enabled: false` is not started |
| `test_stream_status_per_engine` | `tests/test_engine_manager.py` | `/status` contains entries for each active stream |
| `test_trade_tagged_with_stream` | `tests/test_engine_manager.py` | Inserted trade has `stream_name` field |
| `test_trades_filter_by_stream` | `tests/test_engine_manager.py` | `/trades?stream=x` returns only that stream's trades |
| `test_shutdown_stops_all` | `tests/test_engine_manager.py` | `manager.stop()` sets `_running=False` on all engines |
| `test_stream_config_parsing` | `tests/test_config.py` | `forge.json` streams array parsed into `StreamConfig` objects |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots with one stream, runs cycles, dashboard shows stream |
| **Behavior** | All engine-manager tests pass |
| **Contract** | `/status` returns multi-stream shape. Trades include `stream_name`. |
| **Regression** | All existing tests pass (single-stream mode unchanged) |

### G) Implementation Entrypoint Notes

| Component | File | What Changes |
|-----------|------|-------------|
| StreamConfig | `app/models/stream_config.py` | New file |
| Config loader | `app/config.py` | Parse `streams` from `forge.json`, backward compat fallback |
| Engine manager | `app/engine_manager.py` | New file |
| Engine | `app/engine.py` | Accept `StreamConfig`, use `stream_name` for logging/status |
| Routers | `app/api/routers.py` | Multi-stream status dict, `/status/{stream}`, `?stream=` filter |
| Trade repo | `app/repos/trade_repo.py` | Accept/filter `stream_name` column |
| DB migration | `db/migrations/002_add_stream_name.sql` | `ALTER TABLE trades ADD COLUMN stream_name TEXT DEFAULT 'default'` |
| Main | `app/main.py` | Replace single engine with `EngineManager` |
| forge.json | `forge.json` | Add `streams` array |

### H) Dependency Changes

None.

---

## Phase 10 — Trend-Confirmed Micro-Scalp Strategy (XAU_USD)

### A) Purpose and UX Target

Implement a second strategy — "Trend-Confirmed Scalp" — designed for gold (XAU_USD) on fast timeframes (H1 for trend, M1 for entry, S5 for precision). The strategy only enters in the direction of the established trend, executing micro-scalps with tight SL and fixed R:R take-profit. It is registered in the strategy registry so the engine manager can instantiate it when `strategy: "trend_scalp"` is set in `forge.json`.

After this phase, enabling the `micro-scalp` stream in `forge.json` starts a second concurrent engine scalping gold alongside the existing EUR/USD swing trader.

### B) Current Constraints

- Phase 8 delivered `StrategyProtocol` and `calculate_ema()`.
- Phase 9 delivered `EngineManager` and `StreamConfig`.
- `forge.json` has a disabled `micro-scalp` stream placeholder.
- No trend-scalp strategy exists yet.
- `pip_value` for XAU_USD is defined (`0.01`) but untested in live sizing.
- `position_sizer.py` doesn't enforce max concurrent positions.

### C) Scope

#### Constraints
- The trend-scalp strategy is a separate class implementing `StrategyProtocol`.
- It does NOT modify any existing S/R strategy code.
- All new pure functions go in new files under `app/strategy/` and `app/risk/`.
- Risk management additions (trailing stop, position count cap) are generic — they benefit both strategies.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Trend detection** | `app/strategy/trend.py` | `detect_trend(candles_h1, ema_fast=21, ema_slow=50) -> TrendState`. Returns `TrendState(direction="bullish"\|"bearish"\|"flat", ema_fast_value, ema_slow_value, slope)`. Bullish = EMA21 > EMA50 AND price > EMA21. Bearish = inverse. Flat = otherwise. |
| 2 | **Scalp entry signal** | `app/strategy/scalp_signals.py` | `evaluate_scalp_entry(candles_m1, candles_s5, trend: TrendState) -> EntrySignal \| None`. Logic: (a) Price pulls back to EMA(9) on M1. (b) Bullish/bearish engulfing or hammer/shooting-star on the last M1 or S5 candle confirms bounce. (c) Only enters WITH the H1 trend direction. Returns `EntrySignal` with `reason` describing the setup. |
| 3 | **Scalp SL/TP** | `app/risk/scalp_sl_tp.py` | `calculate_scalp_sl(entry_price, direction, candles_m1, lookback=10) -> float`: SL placed 1 pip beyond the most recent M1 swing low (buy) or swing high (sell). Uses `_find_swing_lows`/`_find_swing_highs` from `sr_zones.py` with a window of 2 (tight). `calculate_scalp_tp(entry_price, direction, sl_price, rr_ratio=1.5) -> float`: Fixed R:R target. |
| 4 | **Trailing stop logic** | `app/risk/trailing_stop.py` | `TrailingStop` class. Tracks entry, SL, direction. `update(current_price) -> new_sl_or_None`. Rules: at 1×R profit → move SL to breakeven. At 1.5×R → trail by 0.5×R. Returns updated SL price or None (no change). |
| 5 | **Position count guard** | `app/engine.py` | Before placing an order, check `broker.list_open_positions()` count for the stream's instrument. If `>= max_concurrent_positions` from `StreamConfig`, skip. This applies to all strategies generically. |
| 6 | **Spread filter** | `app/strategy/spread_filter.py` | `is_spread_acceptable(bid, ask, max_spread_pips, pip_value) -> bool`. Compute spread in pips, reject if too wide. For XAU_USD typically max 4 pips ($0.40). Gets bid/ask from the S5 candle (close ≈ mid, spread estimated from high-low of most recent S5). |
| 7 | **Trend-scalp strategy class** | `app/strategy/trend_scalp.py` | `TrendScalpStrategy(StrategyProtocol)`. Orchestrates: fetch H1 → detect trend → if flat, return None → fetch M1 → fetch S5 → check spread → evaluate scalp entry → calculate scalp SL/TP → return `StrategyResult`. |
| 8 | **Strategy registry** | `app/strategy/registry.py` | `STRATEGY_REGISTRY = {"sr_rejection": SRRejectionStrategy, "trend_scalp": TrendScalpStrategy}`. `get_strategy(name) -> StrategyProtocol`. Used by `EngineManager` to instantiate strategy from `StreamConfig.strategy_type`. |
| 9 | **Trailing stop in engine** | `app/engine.py` | After placing an order, if the strategy provides a `TrailingStop`, the engine updates it each cycle by checking current price and adjusting the OANDA SL via a new `broker.modify_trade_sl()` method. *(Stretch goal — defer to Phase 11 if complexity is too high.)* |
| 10 | **Modify SL endpoint** | `app/broker/oanda_client.py` | Add `modify_trade_sl(trade_id, new_sl_price)` method. Calls OANDA `PUT /v3/accounts/{id}/trades/{tradeId}/orders` to update the SL. Needed for trailing stop. |
| 11 | **Gold session filter** | Reuse `session_filter.py` | The existing `is_in_session(utc_hour, start, end)` already works — just configure the scalp stream with `session_start_utc: 7, session_end_utc: 16` in `forge.json` (London open through NY overlap, skip Asia). |
| 12 | **Tests** | `tests/test_trend_scalp.py` | Full test suite for trend detection, scalp signals, scalp SL/TP, trailing stop, spread filter. |

#### Trend-Scalp Strategy Flow

```
TrendScalpStrategy.evaluate(broker, config):
│
├── 1. Fetch 50× H1 candles
│   └── calculate_ema(h1, 21), calculate_ema(h1, 50)
│   └── detect_trend() → TrendState
│   └── if trend == "flat" → return None
│
├── 2. Fetch 20× M1 candles
│   └── check pullback to EMA(9) on M1
│   └── if no pullback → return None
│
├── 3. Fetch 5× S5 candles (precision timing)
│   └── is_spread_acceptable(s5) → if False, return None
│   └── confirm engulfing/hammer pattern on M1 or S5
│   └── if no confirmation → return None
│
├── 4. Calculate scalp SL (swing structure)
│   └── SL = recent M1 swing low/high + 1 pip buffer
│
├── 5. Calculate scalp TP (fixed R:R)
│   └── TP = entry ± (SL distance × 1.5)
│
└── return StrategyResult(signal, sl, tp, atr=None)
```

#### SL/TP Design Detail for Gold Scalps

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **SL method** | Swing-structure: 1 pip beyond most recent M1 swing low (buy) or swing high (sell) | Respects price structure rather than arbitrary ATR multiples. On XAU_USD this typically gives 30–80 pip SL ($3–$8 on gold). |
| **SL minimum** | 15 pips ($1.50) | Prevents SL from being inside the spread noise. If calculated SL is tighter than 15 pips, skip the trade. |
| **SL maximum** | 100 pips ($10.00) | Prevents SL from being too wide for a scalp. If swing structure gives >100 pip SL, skip. |
| **TP method** | Fixed 1:1.5 risk-reward | Scalps prioritize win rate over R:R. 1:1.5 is conservative enough to capture moves without requiring extended runners. |
| **Trailing stop** | At 1×R profit → SL to breakeven. At 1.5×R → trail by 0.5×R. | Locks in profit on winners. Breakeven at 1R means worst case is a scratch, not a loss. |
| **Position size** | `risk_per_trade_pct: 0.25` (from StreamConfig) | 4× smaller than swing trades. Scalps have lower per-trade edge and higher frequency. |
| **Max concurrent** | 3 positions (from StreamConfig) | Caps exposure. At 0.25% risk × 3 = 0.75% total scalp exposure. |
| **Spread filter** | Max 4 pips ($0.40) on XAU_USD | Gold spreads widen in off-hours to 8–15 pips. Scalping into a wide spread is guaranteed loss. |

#### Why This Strategy Won't Buy Counter-Trend

The core safety mechanism is Step 1: **the H1 trend gate**.

- If EMA(21) < EMA(50) on H1 → bearish trend → only **sell** scalps are allowed.
- If EMA(21) > EMA(50) on H1 → bullish trend → only **buy** scalps are allowed.
- If flat (EMAs crossing / interleaved) → **no trades at all**.

The bot will never buy a pullback during a downtrend or sell a rally during an uptrend. It only adds with the trend's momentum, catching micro-pullbacks that resume the macro direction.

The M1 EMA(9) pullback confirmation acts as a second gate — it ensures the scalp entry is at a local discount (buy) or premium (sell) within the trend, not chasing a move that has already extended.

### D) Non-Goals (Explicitly Out of Scope)

- No optimization of EMA periods or R:R ratios (manual tuning first, then consider Phase 11).
- No backtesting of the scalp strategy on S5/M1 data (OANDA historical data for sub-minute is limited; this is a live-forward-test situation).
- No machine learning or adaptive parameter tuning.
- No multi-instrument scanning within one stream (one stream = one instrument).

### E) Acceptance Criteria

#### Functional
1. `detect_trend(h1_candles)` returns `"bullish"` when EMA21 > EMA50 and price above both.
2. `detect_trend(h1_candles)` returns `"bearish"` when EMA21 < EMA50 and price below both.
3. `detect_trend(h1_candles)` returns `"flat"` when EMAs are crossing.
4. `evaluate_scalp_entry()` returns a buy signal only when trend is bullish and M1 shows a confirmed pullback bounce.
5. `evaluate_scalp_entry()` returns `None` when trend is bearish but M1 shows buy setup (counter-trend blocked).
6. Scalp SL is placed at the most recent M1 swing low/high, verified against min/max bounds.
7. Scalp TP = entry + 1.5 × SL distance (for buy), entry - 1.5 × SL distance (for sell).
8. `TrailingStop.update()` moves SL to breakeven at 1R, trails at 1.5R.
9. Spread filter rejects entry when spread > 4 pips.
10. Position count guard prevents 4th concurrent scalp when max is 3.
11. Setting `"enabled": true` on the micro-scalp stream starts the gold scalper alongside EUR/USD swing.
12. Dashboard shows both streams running with independent cycle counts.

#### Unit Tests

| Test case | File | Asserts |
|-----------|------|---------|
| `test_trend_bullish` | `tests/test_trend_scalp.py` | EMA21 > EMA50, price above → bullish |
| `test_trend_bearish` | `tests/test_trend_scalp.py` | EMA21 < EMA50, price below → bearish |
| `test_trend_flat` | `tests/test_trend_scalp.py` | EMAs crossing → flat |
| `test_scalp_buy_with_trend` | `tests/test_trend_scalp.py` | Buy signal when bullish + pullback confirmed |
| `test_scalp_blocked_counter_trend` | `tests/test_trend_scalp.py` | None when bearish but M1 shows buy pattern |
| `test_scalp_sl_swing_low` | `tests/test_trend_scalp.py` | SL at recent M1 swing low for buy |
| `test_scalp_sl_min_bound` | `tests/test_trend_scalp.py` | Trade skipped when SL < 15 pips |
| `test_scalp_sl_max_bound` | `tests/test_trend_scalp.py` | Trade skipped when SL > 100 pips |
| `test_scalp_tp_rr` | `tests/test_trend_scalp.py` | TP = entry ± 1.5 × risk |
| `test_trailing_stop_breakeven` | `tests/test_trend_scalp.py` | SL moves to entry at 1R profit |
| `test_trailing_stop_trail` | `tests/test_trend_scalp.py` | SL trails at 0.5R behind price at 1.5R+ |
| `test_spread_filter_accept` | `tests/test_trend_scalp.py` | Entry allowed when spread < 4 pips |
| `test_spread_filter_reject` | `tests/test_trend_scalp.py` | Entry blocked when spread > 4 pips |
| `test_max_positions_guard` | `tests/test_trend_scalp.py` | Entry skipped when 3 positions already open |
| `test_strategy_registry` | `tests/test_trend_scalp.py` | `get_strategy("trend_scalp")` returns `TrendScalpStrategy` |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes |
| **Runtime** | App boots with both streams enabled, both run cycles (scalp stream may not find signals if market is flat, but it must poll without errors) |
| **Behavior** | All trend-scalp tests pass |
| **Contract** | `TrendScalpStrategy` satisfies `StrategyProtocol`. Dashboard shows both streams. Trades tagged with correct stream. |
| **Regression** | All existing tests pass. S/R swing strategy behavior unchanged. |

### G) Implementation Entrypoint Notes

| Component | File | What Changes |
|-----------|------|-------------|
| Trend detection | `app/strategy/trend.py` | New file |
| Scalp signals | `app/strategy/scalp_signals.py` | New file |
| Scalp SL/TP | `app/risk/scalp_sl_tp.py` | New file |
| Trailing stop | `app/risk/trailing_stop.py` | New file |
| Spread filter | `app/strategy/spread_filter.py` | New file |
| Strategy class | `app/strategy/trend_scalp.py` | New file |
| Strategy registry | `app/strategy/registry.py` | New file |
| Position guard | `app/engine.py` | Add position count check before order placement |
| Modify SL | `app/broker/oanda_client.py` | Add `modify_trade_sl()` method |
| Tests | `tests/test_trend_scalp.py` | New file |

### H) Dependency Changes

None.

### I) Operational Recommendations (Pre-Go-Live)

Before enabling the micro-scalp stream on a practice account:

1. **Run the sr-swing stream alone for 24h** to confirm Phase 9's multi-stream plumbing doesn't break the existing strategy.
2. **Enable micro-scalp with `risk_per_trade_pct: 0.1`** (0.1% = minimal risk) for the first 48h to observe signal quality without meaningful exposure.
3. **Monitor spread behavior** during the first week — if OANDA practice spreads on XAU_USD are consistently >4 pips, widen the filter or switch to a tighter session window.
4. **Trailing stop is a stretch goal** — if it adds too much complexity to Phase 10, defer it to Phase 11 and use fixed TP only at first. Fixed TP is simpler and still profitable if the win rate justifies 1:1.5 R:R.

---

## Phase Summary & Dependency Graph

```
Phase 7: Dashboard            ← no dependency on 8/9/10, can ship first
Phase 8: Strategy Abstraction ← required before 9 and 10
Phase 9: Multi-Stream Engine  ← requires 8
Phase 10: Trend-Scalp Strategy ← requires 8 + 9
```

### Recommended Build Order

| Order | Phase | Est. Complexity | Risk Level |
|-------|-------|----------------|------------|
| 1st | **Phase 7** — Web Dashboard | Low | Read-only, no trade logic changes. Safe to ship immediately. |
| 2nd | **Phase 8** — Strategy Abstraction + EMA | Medium | Refactor of engine core. High test coverage needed to prove no regression. |
| 3rd | **Phase 9** — Multi-Stream Engine Manager | Medium | New orchestration layer. Well-defined boundaries. Must prove backward compat. |
| 4th | **Phase 10** — Trend-Confirmed Micro-Scalp | High | New strategy with new risk model. Requires forward-testing on practice before any live consideration. |

### Global Risk Notes

- **OANDA rate limits**: 120 req/s. Two streams at worst case = ~5 requests per M1-cycle (H1+M1+S5+account+positions) every 5s = 1 req/s. Safe.
- **SQLite concurrency**: Two streams writing trades simultaneously. SQLite handles this with write-ahead logging (WAL mode recommended). Add `PRAGMA journal_mode=WAL` to `init_db()`.
- **Account-level drawdown**: Each stream tracks its own drawdown. A future Phase 11 could add a global account-level circuit breaker that halts ALL streams if total equity drops >15%.
- **Practice vs live divergence**: OANDA practice fills are unrealistically favorable. Scalp performance on practice will be better than live. Plan for a degradation factor when moving to live.

---

## Phase 11 — Momentum Bias Refactor (Scalp Trend Gate Overhaul)

### A) Purpose and Problem Statement

The current trend detection system (`detect_trend()` in `app/strategy/trend.py`) uses a **dual-EMA crossover** with a strict triple-gate:

```
Bullish = EMA(fast) > EMA(slow) AND price > EMA(fast)
Bearish = EMA(fast) < EMA(slow) AND price < EMA(fast)
Flat    = everything else
```

This returns **"flat" approximately 40-50% of the time** on M5 gold, because price frequently sits between the two EMAs or crosses one but not the other. Each "flat" result means zero trades are allowed — the bot sits idle despite valid pullback+confirmation setups being available.

The consequence: **half of all potential trades are locked out** by a trend gate that is too slow and too strict for micro-scalping.

#### What a ~66% Win-Rate Quant Scalper Actually Needs

A professional scalping bot targeting 66% accuracy doesn't need to know "is the market in a trend" — it needs to know **"what direction is price leaning right now"**. The difference is fundamental:

| Aspect | Current (EMA Crossover) | Target (Momentum Bias) |
|---|---|---|
| **Question answered** | "Is the market in a multi-hour trend?" | "What direction has price been moving for the last 15 minutes?" |
| **Lookback** | 30× M5 candles (~2.5 hrs), with EMA lag adding more | 15× M1 candles (~15 minutes) |
| **Method** | Dual EMA crossover + price above both | Majority candle direction + net price change |
| **Flat rate** | ~40-50% of observations | ~5-10% (only when genuinely directionless) |
| **Bias flip speed** | Slow — takes multiple M5 candles to cross back | Fast — flips within 2-3 minutes of reversal |
| **Counter-trend need** | Yes, because trends last hours and you miss reversals | No — bias flips fast enough that you're always "with bias" |

#### Design Rationale

The edge in a scalp is **not** in predicting direction over the next hour — it's in:
1. **Entering pullbacks within the current micro-move** (the M1 EMA(9) proximity check — this stays)
2. **Having a confirmation candle** (engulfing, hammer, pin bar — this stays)
3. **Having a directional lean** so you're not flipping a coin (this is what bias provides)

The bias just needs to answer: "over the last ~15 minutes, is gold moving up or down?" If 9 out of 15 candles are bullish and net price change is positive, that's a bullish bias. You buy pullbacks to EMA(9). If the market reverses, the bias flips within minutes — you start selling pullbacks instead. No more "flat" lockout.

#### Why Counter-Trend Path Becomes Unnecessary

The current code has two entry paths:
- **With-trend**: any confirmation pattern (6 patterns)
- **Counter-trend**: strong reversal only (3 patterns — engulfing, hammer/star, pin bar)

With momentum bias, there is no need for a separate counter-trend path because:
- The bias itself flips when a reversal happens
- A hammer at a swing low will appear when bias is already flipping to bullish
- By the time a reversal is "strong enough" to fire counter-trend, the 15-candle window has already shifted

Removing counter-trend simplifies the code and eliminates the risk of entering against a genuine move.

### B) Current Constraints / Starting State

- `detect_trend()` exists in `app/strategy/trend.py` — a generic function also used by the multi-TF dashboard panel
- `TrendScalpStrategy` in `app/strategy/trend_scalp.py` calls `detect_trend()` with M5 data (fast=9, slow=21)
  - Has a three-tier fallback: M5 → M15 → EMA slope bias
  - Each fallback adds API calls and latency
- `evaluate_scalp_entry()` in `app/strategy/scalp_signals.py` has two paths: with-trend and counter-trend
- Counter-trend path uses `_has_strong_buy()` / `_has_strong_sell()` helper functions
- Dashboard shows "Trend (M5)" label and multi-TF trend cycling
- Tests in `tests/test_trend_scalp.py` test both trend detection and counter-trend entries
- `detect_trend()` is **not** used by the SR-rejection swing strategy (no impact on that stream)
- Multi-TF trend snapshot (dashboard cycling) calls `detect_trend()` with default 21/50 EMAs — purely informational, unaffected by this change

### C) Scope

#### Constraints
- The existing `detect_trend()` function is **NOT modified** — it remains available for the multi-TF dashboard panel and potential future swing use.
- A **new** function `detect_scalp_bias()` is created alongside it.
- Counter-trend entry path is **removed** from `evaluate_scalp_entry()`.
- All confirmation patterns remain unchanged.
- M1 EMA(9) pullback proximity check remains unchanged.
- SL/TP calculation remains unchanged.
- Position sizing, order placement, spread filter — all unchanged.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Momentum bias function** | `app/strategy/trend.py` | New function `detect_scalp_bias(candles_m1, lookback=15, bullish_threshold=0.6, min_net_pips=1.0, pip_value=0.01) -> TrendState`. Returns same `TrendState` dataclass for compatibility. |
| 2 | **Remove M5/M15 trend fetch** | `app/strategy/trend_scalp.py` | Step 1 changes: instead of fetching M5 (30 candles) + M15 fallback + EMA slope fallback, just use the M1 candles (already fetched in step 2) passed to `detect_scalp_bias()`. |
| 3 | **Merge step 1 and 2** | `app/strategy/trend_scalp.py` | Currently: Step 1 = fetch M5 for trend, Step 2 = fetch M1 for pullback. New: Step 1 = fetch M1 (used for both bias detection AND pullback check). Eliminates one API call per cycle. |
| 4 | **Remove counter-trend path** | `app/strategy/scalp_signals.py` | Delete `_has_strong_buy()`, `_has_strong_sell()`, and the "COUNTER-TREND entry" section from `evaluate_scalp_entry()`. The function now only enters with-bias. |
| 5 | **Update insight labels** | `app/strategy/trend_scalp.py` | `self.last_insight["strategy"]` → `"Momentum Scalp"`. Trend dict key `"direction"` remains (dashboard reads it). Add `"bias_method": "M1 momentum"` to insight. |
| 6 | **Update dashboard label** | `app/static/index.html` | Checklist item changes from `"Trend (M5)"` to `"Bias (M1)"`. EMA labels change from `"Trend: EMA(9)"` / `"Trend: EMA(21)"` to `"Bias: bullish"` / `"Bias: bearish"`. |
| 7 | **Update tests** | `tests/test_trend_scalp.py` | New tests for `detect_scalp_bias()`. Remove/update counter-trend test. Update with-trend tests to use bias function. |
| 8 | **Update docstrings** | Multiple files | Update module and function docstrings to reflect momentum bias instead of EMA crossover trend. |

### D) `detect_scalp_bias()` — Detailed Specification

```python
def detect_scalp_bias(
    candles_m1: list[CandleData],
    lookback: int = 15,
    bullish_threshold: float = 0.6,
    min_net_pips: float = 1.0,
    pip_value: float = 0.01,
) -> TrendState:
```

#### Input
- `candles_m1`: M1 candle history, oldest-first. Needs at least `lookback` candles.
- `lookback`: Number of recent candles to analyse (default 15 = 15 minutes).
- `bullish_threshold`: Fraction of candles that must be bullish/bearish to confirm bias (default 0.60 = 60%).
- `min_net_pips`: Minimum net price change (in pips) to break a tie (default 1.0 pip = $0.10 on gold).
- `pip_value`: Pip size for the instrument (default 0.01 for XAU_USD).

#### Algorithm

```
Given the last `lookback` M1 candles:

1. Count bullish candles (close > open) and bearish candles (close < open).
   - Dojis (close == open) are neutral, don't count either way.

2. Calculate net price change = last_close - first_open (over the lookback window).

3. Determine direction:
   a. If bullish_count / total >= bullish_threshold AND net_change > 0:
      → "bullish"
   b. If bearish_count / total >= bullish_threshold AND net_change < 0:
      → "bearish"
   c. Tiebreaker — if neither threshold met but net change is significant:
      - If abs(net_change) >= min_net_pips * pip_value:
        → direction of net_change ("bullish" if positive, "bearish" if negative)
      - Else:
        → "flat"

4. Compute pseudo-slope = net_change / pip_value (in pips, for dashboard display).

5. Return TrendState(direction, ema_fast_value=last_close, ema_slow_value=first_open, slope=pseudo_slope).
   - ema_fast_value and ema_slow_value are repurposed to carry the price window
     endpoints (for dashboard display compatibility).
```

#### Example Scenarios

| Scenario | Bullish/Bearish Count | Net Change | Result |
|----------|----------------------|------------|--------|
| 10 of 15 bullish, gold up $1.50 | 67% bullish | +$1.50 (+150 pips) | **bullish** |
| 9 of 15 bearish, gold down $0.80 | 60% bearish | -$0.80 (-80 pips) | **bearish** |
| 8 of 15 bullish, gold up $0.05 | 53% bullish | +$0.05 (+5 pips) | **bullish** (tiebreaker: net > 1 pip) |
| 8 of 15 bullish, gold down $0.02 | 53% bullish | -$0.02 (-2 pips) | **bearish** (tiebreaker: net is negative and > 1 pip) |
| 7 of 14 bullish (1 doji), gold flat $0.005 | 50/50 | +$0.005 (<1 pip) | **flat** (rare) |
| 11 of 15 bearish, gold up $0.20 | 73% bearish | +$0.20 | **flat** (conflict: candles say bearish but net is up — wait) |

**Conflict handling** (row 6 above): If candle majority says one direction but net price change says the opposite, return "flat". This protects against choppy whipsaw markets where individual candles oscillate but the overall move is the opposite direction. This is the **only** scenario that produces "flat" other than a genuine 50/50 split.

### E) Updated Strategy Flow

```
TrendScalpStrategy.evaluate(broker, config):
│
├── 1. Fetch 20× M1 candles (serves both bias AND pullback)
│   └── detect_scalp_bias(m1_candles, lookback=15) → TrendState
│   └── if bias == "flat" → return None
│
├── 2. M1 EMA(9) pullback proximity check (unchanged)
│   └── price within 0.6% of EMA(9)
│   └── if no pullback → return None
│
├── 3. Fetch 20× S5 candles → spread check (unchanged)
│   └── min S5 range / pip_value > MAX_SPREAD_PIPS → return None
│
├── 4. Confirmation pattern check (unchanged)
│   └── check M1 then S5 for: engulfing, hammer/star, pin bar,
│       momentum (2× consecutive), single candle (body ≥ 40%)
│   └── if no confirmation → return None
│
├── 5. Calculate scalp SL (swing structure — unchanged)
│   └── SL = recent M1 swing low/high + buffer
│
├── 6. Calculate scalp TP (fixed R:R — unchanged)
│   └── TP = entry ± (SL distance × 1.5)
│
└── return StrategyResult(signal, sl, tp, atr=None)
```

#### API Call Reduction

| Step | Before (Phase 10) | After (Phase 11) |
|------|-------------------|-------------------|
| Trend/Bias | Fetch 30× M5 + fallback 50× M15 + EMA calc | **None** (uses M1 from step 2) |
| Pullback | Fetch 20× M1 | Fetch 20× M1 (same) |
| Spread/Confirm | Fetch 20× S5 | Fetch 20× S5 (same) |
| Multi-TF dashboard | 5× fetch (S5, M1, M5, M15, M30) | 5× fetch (unchanged, informational) |
| **Total per cycle** | **8-9 candle requests** | **7 candle requests** (minimum 1, usually 2 fewer) |

### F) Affected Files — Detailed Change Map

| File | Change Type | What Changes |
|------|-------------|-------------|
| `app/strategy/trend.py` | **Add function** | New `detect_scalp_bias()` function. Existing `detect_trend()` untouched. |
| `app/strategy/trend_scalp.py` | **Refactor** | Step 1 replaced: remove M5/M15 fetch + EMA crossover fallback chain. Use M1 candles + `detect_scalp_bias()`. Remove import of `_ema_calc` for slope fallback. Update insight labels. Merge steps 1 and 2 to share M1 fetch. |
| `app/strategy/scalp_signals.py` | **Simplify** | Remove `_has_strong_buy()`, `_has_strong_sell()` helper functions. Remove the entire "COUNTER-TREND entry" section from `evaluate_scalp_entry()`. Remove the `if trend.direction == "flat": return None` guard (bias handles this upstream). |
| `app/static/index.html` | **Label update** | Change checklist item "Trend (M5)" → "Bias (M1)". Update EMA label references in the insight panel. |
| `tests/test_trend_scalp.py` | **Update** | Add `test_bias_bullish`, `test_bias_bearish`, `test_bias_flat_split`, `test_bias_flat_conflict`, `test_bias_tiebreaker_net`. Update `test_scalp_counter_trend_buy_in_bearish` → remove (counter-trend no longer exists). Update strategy integration tests to use bias. |

### G) Non-Goals (Explicitly Out of Scope)

- **No change to `detect_trend()`** — the existing function stays for multi-TF dashboard and potential swing strategy use.
- **No change to SL/TP logic** — swing structure SL and fixed R:R TP are unchanged.
- **No change to position sizing or risk management** — `calculate_units()`, drawdown tracker, circuit breaker are unchanged.
- **No change to the SR-rejection swing strategy** — this phase only affects the scalp pipeline.
- **No change to order placement** — the pip_value, integer units, and price precision fixes from the previous commit are unchanged.
- **No adaptive/ML tuning of bias parameters** — `lookback=15`, `threshold=0.6`, `min_net_pips=1.0` are hardcoded. Future phase could make these configurable via `forge.json`.
- **No backtesting** — M1 historical data is limited; this is validated via forward-testing on practice.

### H) Acceptance Criteria

#### Functional

1. `detect_scalp_bias()` returns `"bullish"` when ≥60% of last 15 M1 candles are bullish AND net price change is positive.
2. `detect_scalp_bias()` returns `"bearish"` when ≥60% of last 15 M1 candles are bearish AND net price change is negative.
3. `detect_scalp_bias()` returns `"flat"` when candle majority conflicts with net price direction (whipsaw protection).
4. `detect_scalp_bias()` uses net price tiebreaker when neither side reaches 60% but net change exceeds 1 pip.
5. `detect_scalp_bias()` returns `"flat"` when 50/50 split and net change < 1 pip.
6. `evaluate_scalp_entry()` no longer has a counter-trend path — it only enters with-bias.
7. `TrendScalpStrategy.evaluate()` fetches M1 candles once (shared between bias and pullback checks), not separately for M5 trend + M1 pullback.
8. The multi-TF trend cycling dashboard panel continues to work (it uses `detect_trend()`, which is unchanged).
9. The strategy insight panel shows "Momentum Scalp" as the strategy name and "Bias (M1)" labels.
10. The bot fires trades when bias is bullish or bearish + pullback + confirmation — no more extended "flat" lockouts during active gold sessions.

#### Unit Tests

| Test Case | File | Asserts |
|-----------|------|---------|
| `test_bias_bullish` | `tests/test_trend_scalp.py` | 10/15 bullish candles + net positive → `"bullish"` |
| `test_bias_bearish` | `tests/test_trend_scalp.py` | 10/15 bearish candles + net negative → `"bearish"` |
| `test_bias_flat_5050` | `tests/test_trend_scalp.py` | 7/14 bullish (1 doji) + net < 1 pip → `"flat"` |
| `test_bias_flat_conflict` | `tests/test_trend_scalp.py` | 11/15 bearish candles + net positive → `"flat"` (conflict) |
| `test_bias_tiebreaker_net` | `tests/test_trend_scalp.py` | 8/15 bullish + net > 1 pip → direction of net change |
| `test_bias_short_candles` | `tests/test_trend_scalp.py` | Fewer than `lookback` candles → `"flat"` (insufficient data) |
| `test_scalp_buy_with_bias` | `tests/test_trend_scalp.py` | Bullish bias + pullback + confirmation → buy signal |
| `test_scalp_sell_with_bias` | `tests/test_trend_scalp.py` | Bearish bias + pullback + confirmation → sell signal |
| `test_no_counter_trend_entry` | `tests/test_trend_scalp.py` | Bullish bias + bearish engulfing → `None` (with-bias only) |
| `test_strategy_uses_m1_for_bias` | `tests/test_trend_scalp.py` | Strategy does NOT fetch M5 candles for trend (verify mock call count) |

### I) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes. No import errors. |
| **Runtime** | App boots with micro-scalp stream enabled. Cycles run without errors. Bias detection fires on each cycle. |
| **Behavior** | All new and updated tests pass. Existing test count stays at 143+ passing. |
| **Contract** | `TrendScalpStrategy` still satisfies `StrategyProtocol`. Dashboard shows correct labels. Signal log records bias-based entries. |
| **Regression** | SR-rejection swing strategy unaffected. `detect_trend()` function unchanged. Multi-TF dashboard panel unchanged. |

### J) Operational Notes

#### Tuning Guidance (Post-Deploy)

After running on practice for 48-72 hours with the new bias system, evaluate:

| Parameter | Default | If too few trades | If too many bad trades |
|-----------|---------|-------------------|----------------------|
| `lookback` | 15 (minutes) | Decrease to 10 | Increase to 20 |
| `bullish_threshold` | 0.60 (60%) | Decrease to 0.55 | Increase to 0.65 |
| `min_net_pips` | 1.0 ($0.10) | Decrease to 0.5 | Increase to 2.0 |
| Pullback `0.6%` | 0.6% | Widen to 0.8% | Tighten to 0.4% |

These parameters are hardcoded in Phase 11. A future phase could expose them in `forge.json` stream config.

#### Expected Improvement

| Metric | Before (EMA Crossover) | After (Momentum Bias) | Reasoning |
|--------|----------------------|----------------------|-----------|
| Flat rate | ~40-50% | ~5-10% | Only 50/50 splits or conflict yield flat |
| Trades per session | 2-5 | 5-12 | More opportunities pass the bias gate |
| Win rate | ~60% (theoretical) | ~62-66% | Same pullback+confirmation edge, fewer forced counter-trend entries |
| API calls per cycle | 8-9 | 7 | No M5/M15 trend fetch |
| Cycle time | ~3-4s | ~2-3s | Fewer API calls |

### K) Build Steps (For Builder Reference)

The builder should execute these steps in order:

1. **Add `detect_scalp_bias()`** to `app/strategy/trend.py` — pure function, no side effects, fully testable in isolation.
2. **Write bias unit tests** in `tests/test_trend_scalp.py` — all 6 bias tests should pass before touching the strategy.
3. **Refactor `TrendScalpStrategy.evaluate()`** in `app/strategy/trend_scalp.py` — replace M5/M15 trend chain with M1 bias call. Merge steps 1+2 to share M1 fetch.
4. **Remove counter-trend from `evaluate_scalp_entry()`** in `app/strategy/scalp_signals.py` — delete `_has_strong_buy`, `_has_strong_sell`, and the counter-trend section.
5. **Update dashboard labels** in `app/static/index.html`.
6. **Update/add integration tests** — verify strategy uses M1 for bias, no M5 fetch, no counter-trend entry.
7. **Run full test suite** — 143+ passing, 1 pre-existing failure.
8. **Boot and smoke test** — start bot, verify dashboard shows "Bias (M1)" and "Momentum Scalp", verify signal log shows bias-based entries.
9. **Commit**.

---

## Phase 12 — Mean Reversion Strategy for EUR/USD

### A) Purpose and Problem Statement

Forex major pairs (EUR/USD, GBP/USD, USD/JPY) spend approximately **70% of their time in ranges** — oscillating between support and resistance. The current `sr_rejection` strategy already detects S/R zones and rejection wicks, but it is a swing strategy on D+H4 timeframes that trades infrequently (a few signals per week at most).

A **mean reversion strategy** exploits the ranging nature of forex by:
- Detecting when the market is ranging (not trending)
- Buying at the bottom of the range when oversold
- Selling at the top of the range when overbought
- Exiting at the midpoint or opposite boundary

This is the **highest win-rate systematic approach** in forex, typically achieving **68-75% accuracy** when filtered with ADX to avoid trending markets. The edge comes from a statistical truth: most S/R breakout attempts fail. Prices bounce off boundaries far more often than they break through them.

#### Why This Beats Trend-Following on Accuracy

| Aspect | Trend Following | Mean Reversion |
|--------|----------------|----------------|
| Win rate | 38-45% | 68-75% |
| R:R per trade | 2:1 to 3:1 | 1:1 to 1:1.2 |
| Holding time | Hours to days | 1-8 hours |
| Works when | Market is trending | Market is ranging (70% of the time) |
| Fails when | Market is choppy | Range breaks out into trend |
| Drawdown pattern | Many small losses, few big wins | Steady small wins, occasional larger loss |

The mean reversion strategy complements the existing scalp and swing strategies — it trades a different market condition (range vs trend vs momentum).

### B) Current Constraints / Starting State

- `sr_zones.py` exists — detects support/resistance zones from swing highs/lows. Can be reused.
- `indicators.py` has ATR(14) and EMA(n). **No RSI or ADX yet**.
- `StrategyProtocol` is established — new strategy must implement `evaluate(broker, config) -> Optional[StrategyResult]`.
- `StreamConfig` supports arbitrary strategy names, timeframes, risk, session filters.
- Strategy registry (`registry.py`) handles instantiation from config.
- The `sr-swing` stream currently uses `sr_rejection` on EUR/USD D+H4. The new strategy would be a **separate stream** that can coexist.
- Dashboard insight panel already supports multiple streams with tabs.

### C) Scope

#### Constraints
- The mean reversion strategy is a **new class** implementing `StrategyProtocol`.
- It does NOT modify any existing strategy code (SR-rejection, momentum scalp).
- New indicators (RSI, ADX) go in `app/strategy/indicators.py` as pure functions.
- The strategy operates on **H1 timeframe** for zone detection and **M15** for entry timing — fast enough for intraday mean reversion but not so fast that it becomes scalping.
- No new dependencies — pure Python, no external libraries needed.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **RSI indicator** | `app/strategy/indicators.py` | `calculate_rsi(candles, period=14) -> list[float]`. Standard Wilder's RSI. Returns full series. |
| 2 | **ADX indicator** | `app/strategy/indicators.py` | `calculate_adx(candles, period=14) -> list[float]`. Standard ADX from +DI, -DI, DX smoothing. Returns full series. |
| 3 | **Bollinger Bands** | `app/strategy/indicators.py` | `calculate_bollinger(candles, period=20, std_dev=2.0) -> tuple[list[float], list[float], list[float]]`. Returns (upper, middle, lower) band series. |
| 4 | **Range detection** | `app/strategy/mean_reversion.py` | `is_ranging(adx_values, threshold=25.0) -> bool`. Returns True when latest ADX < threshold. This is the critical filter — only trade when the market is NOT trending. |
| 5 | **Mean reversion signal evaluator** | `app/strategy/mr_signals.py` | `evaluate_mr_entry(candles_m15, rsi_values, bb_upper, bb_lower, bb_mid, zones, trend_state) -> Optional[MREntrySignal]`. Core logic: buy when price at lower BB/support + RSI < 30; sell when price at upper BB/resistance + RSI > 70. |
| 6 | **Mean reversion strategy class** | `app/strategy/mean_reversion.py` | `MeanReversionStrategy(StrategyProtocol)`. Orchestrates the full pipeline. |
| 7 | **SL/TP for mean reversion** | `app/risk/mr_sl_tp.py` | SL just beyond range boundary. TP at midpoint (conservative) or opposite boundary (aggressive). |
| 8 | **Register strategy** | `app/strategy/registry.py` | Add `"mean_reversion": MeanReversionStrategy` to registry. |
| 9 | **Add stream to forge.json** | `forge.json` | New `"mr-range"` stream for EUR/USD on H1+M15, enabled=false by default. |
| 10 | **Tests** | `tests/test_mean_reversion.py` | Full test suite for RSI, ADX, Bollinger, range detection, signal evaluation, strategy integration. |

### D) New Indicator Specifications

#### RSI (Relative Strength Index)

```python
def calculate_rsi(candles: list[CandleData], period: int = 14) -> list[float]:
```

**Algorithm** (Wilder's smoothed RSI):
1. Calculate price changes: `delta = close[i] - close[i-1]`
2. Separate gains (positive deltas) and losses (abs of negative deltas).
3. First average gain/loss = SMA of first `period` values.
4. Subsequent: `avg_gain = (prev_avg_gain × (period-1) + current_gain) / period` (Wilder smoothing).
5. RS = avg_gain / avg_loss
6. RSI = 100 - (100 / (1 + RS))

**Returns**: Full-length list. Values before seed period are `NaN`. Range: 0-100.

**Key levels**:
- RSI < 30 = oversold (buy signal in ranging market)
- RSI > 70 = overbought (sell signal in ranging market)
- RSI 40-60 = neutral (no signal)

#### ADX (Average Directional Index)

```python
def calculate_adx(candles: list[CandleData], period: int = 14) -> list[float]:
```

**Algorithm**:
1. Calculate +DM (Directional Movement) and -DM for each candle:
   - `+DM = high[i] - high[i-1]` if positive and > `-(low[i] - low[i-1])`, else 0
   - `-DM = low[i-1] - low[i]` if positive and > `+(high[i] - high[i-1])`, else 0
2. Smooth +DM, -DM, and TR using Wilder smoothing (same as RSI).
3. `+DI = 100 × smoothed_+DM / smoothed_TR`
4. `-DI = 100 × smoothed_-DM / smoothed_TR`
5. `DX = 100 × |+DI - -DI| / (+DI + -DI)`
6. ADX = Wilder-smoothed DX over `period`.

**Returns**: Full-length list. Needs `2 × period + 1` candles minimum. Values before seed are `NaN`.

**Key levels**:
- ADX < 20 = strong range (ideal for mean reversion)
- ADX 20-25 = weak range / transition (acceptable)
- ADX > 25 = trending (DO NOT trade mean reversion)
- ADX > 40 = strong trend (definitely do not trade)

#### Bollinger Bands

```python
def calculate_bollinger(
    candles: list[CandleData],
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[list[float], list[float], list[float]]:
```

**Algorithm**:
1. Middle band = SMA(close, period)
2. Standard deviation = σ of last `period` closes
3. Upper band = middle + (std_dev × σ)
4. Lower band = middle - (std_dev × σ)

**Returns**: Tuple of (upper, middle, lower) band series. Each is full-length with `NaN` before seed.

**Usage in mean reversion**:
- Price touching lower band + RSI < 30 → oversold at range bottom
- Price touching upper band + RSI > 70 → overbought at range top
- Price near middle band → no signal (wait for extremes)

### E) Mean Reversion Strategy Flow

```
MeanReversionStrategy.evaluate(broker, config):
│
├── 1. Fetch 50× H1 candles
│   └── calculate_adx(h1, 14) → ADX series
│   └── if ADX[-1] > 25 → return None (market is trending, not ranging)
│   └── detect_sr_zones(h1) → zone list (reuse existing S/R detection)
│
├── 2. Fetch 30× M15 candles
│   └── calculate_rsi(m15, 14) → RSI series
│   └── calculate_bollinger(m15, 20, 2.0) → (upper, middle, lower)
│
├── 3. Evaluate mean reversion entry
│   └── BUY conditions (ALL must be true):
│       a. ADX < 25 (ranging)
│       b. Price at or below lower Bollinger Band
│       c. RSI(14) < 30 (oversold)
│       d. Price within 15 pips of a support zone (S/R confirmation)
│   └── SELL conditions (ALL must be true):
│       a. ADX < 25 (ranging)
│       b. Price at or above upper Bollinger Band
│       c. RSI(14) > 70 (overbought)
│       d. Price within 15 pips of a resistance zone (S/R confirmation)
│   └── if neither → return None
│
├── 4. Calculate SL
│   └── BUY: SL = max(zone_price - 1.5×ATR, lower_bb - 1.5×ATR)
│   └── SELL: SL = min(zone_price + 1.5×ATR, upper_bb + 1.5×ATR)
│   └── Just beyond range boundary — if it breaks, range is invalid
│
├── 5. Calculate TP
│   └── Conservative: Bollinger middle band (midpoint of range)
│   └── Aggressive: opposite Bollinger band (full range traverse)
│   └── Default: use middle band (higher win rate)
│
├── 6. ADX kill-switch flag
│   └── Store current ADX in result metadata
│   └── Engine can close early if ADX spikes above 30 while in trade
│       (stretch goal — defer if too complex)
│
└── return StrategyResult(signal, sl, tp, atr)
```

#### API Call Summary

| Step | Fetch | Count | Purpose |
|------|-------|-------|---------|
| 1 | H1 candles | 50 | ADX(14) + S/R zone detection |
| 2 | M15 candles | 30 | RSI(14) + Bollinger Bands(20, 2.0) |
| **Total** | **2 requests per cycle** | | Very light — no multi-TF cascading |

### F) Entry Signal Detail

#### Buy Entry (Oversold at Range Bottom)

```
Required (ALL):
  ├── ADX(14) on H1 < 25                 → market is ranging
  ├── Price ≤ Bollinger Lower Band (M15)  → at range bottom
  ├── RSI(14) on M15 < 30                → oversold confirmation
  └── Price within 15 pips of support     → S/R zone agreement

Optional bonus (logged but not required):
  ├── RSI divergence (price lower low, RSI higher low) → extra confidence
  └── Bullish candle pattern on M15       → immediate bounce signal
```

#### Sell Entry (Overbought at Range Top)

```
Required (ALL):
  ├── ADX(14) on H1 < 25                 → market is ranging
  ├── Price ≥ Bollinger Upper Band (M15)  → at range top
  ├── RSI(14) on M15 > 70                → overbought confirmation
  └── Price within 15 pips of resistance  → S/R zone agreement

Optional bonus (logged but not required):
  ├── RSI divergence (price higher high, RSI lower high) → extra confidence
  └── Bearish candle pattern on M15       → immediate rejection signal
```

#### Why Four Gates?

Each gate independently filters noise. Together they produce high accuracy:

| Gate | Purpose | False signals filtered |
|------|---------|----------------------|
| ADX < 25 | Only trade when ranging | Eliminates all trend trades (≈30% of time) |
| Bollinger touch | Price at extreme | Eliminates mid-range noise (≈80% of candles) |
| RSI < 30 / > 70 | Momentum exhaustion | Eliminates moves with momentum behind them |
| S/R zone proximity | Structural validation | Eliminates extremes at non-significant levels |

Probability of all four aligning on a losing trade is significantly lower than any single indicator.

### G) SL/TP Design for Mean Reversion

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| **SL method** | 1.5 × ATR(14) beyond the nearest zone/BB boundary | If price moves this far past the boundary, the range has broken. Get out. |
| **SL minimum** | 10 pips | Prevents SL inside spread noise on EUR/USD. |
| **SL maximum** | 50 pips | Caps risk for a mean reversion trade. If SL needs to be wider, the range is too large for this strategy. |
| **TP method** | Bollinger middle band (default) | Conservative target — price returns to average. Higher hit rate than full-range TP. |
| **TP alternative** | Opposite Bollinger band | Aggressive — captures full range. Lower hit rate but better R:R. Configurable via `rr_mode` param. |
| **Expected R:R** | 1:1 to 1:1.2 (middle band TP) | Mean reversion sacrifices R:R for win rate. At 72% accuracy, 1:1 R:R is profitable (EV = +$0.44 per $1 risked). |
| **Position size** | `risk_per_trade_pct: 0.75` | Larger than scalp (0.5%) because higher confidence, smaller than swing (1.0%) because shorter holding time. |
| **Max concurrent** | 1 | Mean reversion on one pair — no stacking positions at the same level. |

### H) Dashboard Integration

The strategy populates `self.last_insight` with:

```python
{
    "strategy": "Mean Reversion",
    "pair": "EUR_USD",
    "checks": {
        "range_detected": True/False,    # ADX < 25
        "at_boundary": True/False,       # price at BB edge
        "rsi_extreme": True/False,       # RSI < 30 or > 70
        "zone_confirmed": True/False,    # near S/R zone
        "sl_valid": True/False,
        "risk_calculated": True/False,
    },
    "adx": 18.5,
    "rsi": 27.3,
    "bb_upper": 1.0865,
    "bb_middle": 1.0842,
    "bb_lower": 1.0819,
    "nearest_zone": {"price": 1.0821, "type": "support", "distance_pips": 2.3},
    "result": "signal_found" | "trending" | "not_at_boundary" | "rsi_neutral" | "no_zone",
}
```

The existing dashboard insight panel renders this automatically — the `checks` dict drives the readiness checklist, and numeric values appear in the stats section.

### I) forge.json Stream Configuration

```json
{
    "name": "mr-range",
    "instrument": "EUR_USD",
    "strategy": "mean_reversion",
    "timeframes": ["H1", "M15"],
    "poll_interval_seconds": 120,
    "risk_per_trade_pct": 0.75,
    "max_concurrent_positions": 1,
    "session_start_utc": 7,
    "session_end_utc": 20,
    "enabled": false
}
```

**Notes**:
- `poll_interval_seconds: 120` — checks every 2 minutes. Mean reversion doesn't need sub-minute polling.
- `enabled: false` — must be explicitly enabled after forward-testing.
- Same session window as SR-swing (London+NY). Ranges are most reliable mid-session.
- Runs on EUR/USD alongside the existing `sr-swing` stream. They won't conflict — `sr-swing` looks for rejection wicks at D/H4 zones (different timeframe, different condition), `mr-range` looks for BB+RSI extremes at H1/M15 zones (only when ADX says ranging).

### J) Interaction with Existing sr-swing Stream

Both `sr-swing` and `mr-range` trade EUR/USD. They could potentially signal at the same time. This is handled by:

1. **Different conditions**: `sr-swing` requires a rejection wick on H4 near a Daily zone. `mr-range` requires ADX < 25, BB touch, RSI extreme on M15 near an H1 zone. Both signaling simultaneously is unlikely but not impossible — and if they agree, that's actually strong confirmation.

2. **Position guard**: `max_concurrent_positions: 1` on each stream. The engine checks open positions per instrument. If `sr-swing` already has an EUR/USD position open, `mr-range` can still open another (they're independent streams with independent position counts). Total max = 2 EUR/USD positions.

3. **Conflicting directions**: If `sr-swing` says buy and `mr-range` says sell, both execute. This is acceptable — they're different strategies with different holding times. The mean reversion trade will close faster (hours vs days).

### K) Non-Goals (Explicitly Out of Scope)

- **No RSI divergence detection** — divergence is a bonus signal, not a gate. Detecting it requires multi-swing analysis that adds complexity. Defer to future phase.
- **No ADX kill-switch in engine** — closing a trade mid-flight because ADX spiked is the stretch goal. Phase 12 focuses on entry logic. The SL handles adverse moves.
- **No Bollinger Band squeeze detection** — squeeze (bands narrowing) predicts expansion but not direction. Could be a future enhancement.
- **No multi-pair mean reversion** — Phase 12 targets EUR/USD only. Could extend to GBP/USD, USD/JPY in a future phase once the strategy is validated.
- **No pairs/correlation trading** — trading the EUR/USD vs GBP/USD spread is a separate, more complex strategy. Out of scope.
- **No ML/optimization of indicator periods** — RSI(14), ADX(14), BB(20, 2.0) are standard settings. Tuning is manual and deferred.

### L) Acceptance Criteria

#### Functional

1. `calculate_rsi()` returns correct RSI values matching known test data (verified against manual calculation).
2. `calculate_rsi()` returns RSI < 30 for oversold synthetic data and RSI > 70 for overbought synthetic data.
3. `calculate_adx()` returns ADX < 20 for flat/ranging synthetic candles.
4. `calculate_adx()` returns ADX > 30 for strongly trending synthetic candles.
5. `calculate_bollinger()` returns bands that widen during volatility and narrow during calm.
6. `is_ranging()` returns True when ADX < 25, False otherwise.
7. `evaluate_mr_entry()` returns buy when all four gates pass (ADX ranging + lower BB + RSI < 30 + support zone).
8. `evaluate_mr_entry()` returns sell when all four gates pass (ADX ranging + upper BB + RSI > 70 + resistance zone).
9. `evaluate_mr_entry()` returns None when ADX > 25 (trending — even if RSI and BB say go).
10. `evaluate_mr_entry()` returns None when RSI is between 30-70 (not at extreme).
11. SL is placed beyond the range boundary. TP at Bollinger midpoint by default.
12. SL min/max bounds (10-50 pips) are enforced.
13. Strategy registers as `"mean_reversion"` and is instantiated correctly.
14. Dashboard insight panel shows ADX, RSI, BB levels, and range check status.
15. Setting `"enabled": true` on the `mr-range` stream starts the strategy alongside existing streams.

#### Unit Tests

| Test Case | File | Asserts |
|-----------|------|---------|
| `test_rsi_oversold` | `tests/test_mean_reversion.py` | RSI < 30 for steadily dropping prices |
| `test_rsi_overbought` | `tests/test_mean_reversion.py` | RSI > 70 for steadily rising prices |
| `test_rsi_neutral` | `tests/test_mean_reversion.py` | RSI 40-60 for flat prices |
| `test_rsi_insufficient_data` | `tests/test_mean_reversion.py` | ValueError when < period+1 candles |
| `test_adx_ranging` | `tests/test_mean_reversion.py` | ADX < 20 for oscillating prices |
| `test_adx_trending` | `tests/test_mean_reversion.py` | ADX > 30 for consistently rising prices |
| `test_adx_insufficient_data` | `tests/test_mean_reversion.py` | ValueError when < 2×period+1 candles |
| `test_bollinger_bands_width` | `tests/test_mean_reversion.py` | Upper > middle > lower. Width increases with volatility. |
| `test_is_ranging_true` | `tests/test_mean_reversion.py` | `is_ranging(adx, 25)` True when ADX = 18 |
| `test_is_ranging_false` | `tests/test_mean_reversion.py` | `is_ranging(adx, 25)` False when ADX = 32 |
| `test_mr_buy_signal` | `tests/test_mean_reversion.py` | Buy when all four gates pass |
| `test_mr_sell_signal` | `tests/test_mean_reversion.py` | Sell when all four gates pass |
| `test_mr_blocked_trending` | `tests/test_mean_reversion.py` | None when ADX > 25 |
| `test_mr_blocked_rsi_neutral` | `tests/test_mean_reversion.py` | None when RSI is 50 |
| `test_mr_blocked_no_zone` | `tests/test_mean_reversion.py` | None when no S/R zone nearby |
| `test_mr_sl_bounds` | `tests/test_mean_reversion.py` | SL None when < 10 pips or > 50 pips |
| `test_mr_tp_midpoint` | `tests/test_mean_reversion.py` | TP = Bollinger middle band |
| `test_strategy_registry` | `tests/test_mean_reversion.py` | `get_strategy("mean_reversion")` returns instance |
| `test_strategy_protocol` | `tests/test_mean_reversion.py` | `isinstance(strat, StrategyProtocol)` |

### M) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | `python -m compileall app/` passes. No import errors. |
| **Runtime** | App boots with `mr-range` stream enabled. Cycles run without errors. |
| **Behavior** | All mean reversion tests pass. Existing tests unaffected (150+ passing). |
| **Contract** | `MeanReversionStrategy` satisfies `StrategyProtocol`. Dashboard shows stream. |
| **Regression** | SR-rejection and momentum scalp strategies unchanged and passing. |

### N) Affected Files — Change Map

| File | Change Type | What Changes |
|------|-------------|-------------|
| `app/strategy/indicators.py` | **Add functions** | New `calculate_rsi()`, `calculate_adx()`, `calculate_bollinger()`. Existing ATR/EMA untouched. |
| `app/strategy/mean_reversion.py` | **New file** | `MeanReversionStrategy` class + `is_ranging()` helper. |
| `app/strategy/mr_signals.py` | **New file** | `MREntrySignal` dataclass + `evaluate_mr_entry()` function. |
| `app/risk/mr_sl_tp.py` | **New file** | `calculate_mr_sl()`, `calculate_mr_tp()`. |
| `app/strategy/registry.py` | **Add entry** | Register `"mean_reversion"`. |
| `forge.json` | **Add stream** | New `"mr-range"` stream (disabled by default). |
| `tests/test_mean_reversion.py` | **New file** | Full test suite (19 tests). |

### O) Build Steps (For Builder Reference)

1. **Add RSI to `indicators.py`** — pure function, fully testable in isolation. Write test immediately.
2. **Add ADX to `indicators.py`** — depends on nothing. Write test immediately.
3. **Add Bollinger Bands to `indicators.py`** — uses SMA. Write test immediately.
4. **Run indicator tests** — all three indicators pass before touching strategy code.
5. **Create `mr_signals.py`** — `MREntrySignal` dataclass + `evaluate_mr_entry()`. Write signal tests.
6. **Create `mr_sl_tp.py`** — SL/TP calculation for mean reversion. Write SL/TP tests.
7. **Create `mean_reversion.py`** — strategy class orchestrating the pipeline. Write integration test.
8. **Register strategy** — add to `registry.py`. Write registry test.
9. **Add `mr-range` stream to `forge.json`** — disabled by default.
10. **Run full test suite** — 150+ existing + 19 new all passing.
11. **Boot and smoke test** — enable `mr-range`, start bot, verify dashboard shows three streams.
12. **Commit**.

### P) Operational Notes (Post-Deploy)

#### Tuning Guidance

| Parameter | Default | If too few trades | If too many bad trades |
|-----------|---------|-------------------|----------------------|
| ADX threshold | 25 | Raise to 30 (allows weaker ranges) | Lower to 20 (stricter ranging) |
| RSI oversold | 30 | Raise to 35 | Lower to 25 |
| RSI overbought | 70 | Lower to 65 | Raise to 75 |
| BB std_dev | 2.0 | Lower to 1.5 (tighter bands = more touches) | Raise to 2.5 (only extreme touches) |
| Zone proximity | 15 pips | Widen to 25 pips | Tighten to 10 pips |
| TP target | Middle band | Switch to opposite band (more profit per trade) | Keep middle (higher win rate) |

#### Expected Performance

| Metric | Projected |
|--------|----------|
| Win rate | 68-75% |
| R:R | 1:1 to 1:1.2 |
| Trades per week | 3-8 (EUR/USD ranges regularly but not constantly) |
| Avg holding time | 2-8 hours |
| Max drawdown per trade | 50 pips ($50 at 0.75% risk on $10k = ~$75 risk) |
| Expected monthly return | +2-4% on capital (at 72% WR, 1:1 RR, 5 trades/week) |

---

## Phase 13 — Reinforcement Learning Trade Filter (XAU/USD — "ForgeAgent")

### A) Purpose and Problem Statement

The momentum-bias micro-scalp strategy (Phase 10/11) generates entry signals based on a fixed rule pipeline: bias detection → EMA pullback → confirmation pattern → SL/TP calculation. Every signal that passes all checks is executed. The problem is that **not all passing signals are equal in quality**, and the rule-based system has no mechanism to distinguish between:

- A pullback to EMA(9) during a strong, clean directional move with tight consolidation at a significant structural level → **high-quality setup**
- A pullback to EMA(9) after an overextended move near a round number, late in the session, with widening spreads and choppy M1 candles → **low-quality setup that will get stopped out**

Both pass every check. Both get traded. The second one produces losses like the XAU/USD LONG at 5000.25 that hit SL at 4992.95 in 15 minutes for a -$3,124 loss.

**Reinforcement Learning (RL) adds a learned quality filter** on top of the existing rule-based pipeline. The RL agent — **ForgeAgent** — doesn't replace the strategy logic. It answers one question: *"Given everything I can observe about the current market state, should I let this trade through or veto it?"*

The agent learns this judgment from thousands of simulated trades on historical Gold data, discovering patterns that no hand-coded rule can capture — session-dependent behaviour, volatility regime shifts, price psychology at round numbers, spread-to-ATR cost ratios, and the complex interactions between all of these.

#### Why RL and Not a Simple Classifier

A rules-based filter (e.g., "don't trade after 21:00 UTC") is brittle — it encodes a single observation as a hard boundary. RL learns a **continuous confidence surface** across the entire state space. It might learn that trading at 21:30 is bad when ATR is declining and price is near a round number, but acceptable at 21:30 when ATR is spiking from a news event with strong directional momentum. No hand-written rule captures this nuance.

A traditional ML classifier (logistic regression, random forest) could learn some of this, but it treats each trade independently. RL is specifically designed for **sequential decision-making** — it considers the impact of each decision on future outcomes (e.g., "if I take this marginal trade and lose, my drawdown increases, which affects my next decision"). The Markov Decision Process formulation naturally handles account state, recent performance streaks, and compounding effects.

### B) Architecture Overview

```
                                    ┌─────────────────────────────┐
                                    │     ForgeAgent (RL Model)   │
                                    │                             │
   ┌─────────────┐                  │  ┌───────────────────────┐  │
   │  Historical  │──── train ──────▶  │   PPO Policy Network  │  │
   │  Gold Data   │                 │  │   (Actor + Critic)    │  │
   └─────────────┘                  │  └───────────┬───────────┘  │
                                    │              │              │
   ┌─────────────┐                  │              ▼              │
   │  Gym Env    │◀─── step ────────│      action: TAKE / VETO   │
   │ (Simulator) │──── state ──────▶│                             │
   └─────────────┘                  └─────────────────────────────┘
                                                   │
                                                   │ (deploy)
                                                   ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                        Live Engine                              │
   │                                                                 │
   │  TrendScalpStrategy.evaluate() → StrategyResult                 │
   │      │                                                          │
   │      ▼                                                          │
   │  ForgeAgent.assess(state_vector) → confidence (0.0 – 1.0)      │
   │      │                                                          │
   │      ├── confidence > threshold → EXECUTE trade                 │
   │      └── confidence ≤ threshold → VETO (log and skip)           │
   │                                                                 │
   └─────────────────────────────────────────────────────────────────┘
```

### C) Phase 13 Sub-Phase Breakdown

Phase 13 is divided into seven sequential sub-phases, each with its own acceptance criteria. They must be built and verified in order.

| Sub-Phase | Name | Depends On | Est. Complexity |
|-----------|------|-----------|-----------------|
| **13.0** | Data Collection Pipeline | Phases 10-12 complete, OANDA API access | Low-Medium |
| **13.1** | Feature Engineering (State Vector) | 13.0 | Medium |
| **13.2** | Gym Environment Design | 13.0, 13.1 | High |
| **13.3** | Reward Shaping | 13.2 | High (most critical design work) |
| **13.4** | Neural Network Architecture | 13.2, 13.3 | Medium |
| **13.5** | Training Pipeline | 13.1–13.4 | Medium |
| **13.6** | Evaluation & Walk-Forward Validation | 13.5 | Medium |
| **13.7** | Live Integration (Shadow → Active) | 13.6 passing evaluation thresholds | Low |

---

### Phase 13.0 — Data Collection Pipeline

#### Purpose

Download, validate, store, and serve historical XAU/USD candle data across multiple timeframes for RL training. This is the foundation everything else depends on — without sufficient quality data, the agent cannot learn meaningful patterns.

#### Data Requirements

| Timeframe | Purpose | Candles Needed | Period | Source |
|-----------|---------|---------------|--------|--------|
| **M5** | Primary decision timeframe (matches live scalp cadence) | ~175,000 | 12 months | OANDA v20 REST API |
| **M1** | Intra-candle simulation for trade outcomes (SL/TP hit detection) | ~520,000 | 12 months | OANDA v20 REST API |
| **H1** | Trend/volatility context features | ~6,000 | 12 months | OANDA v20 REST API |
| **M15** | RSI/BB context for mean-reversion regime detection | ~35,000 | 12 months | OANDA v20 REST API |

**Total**: ~736,000 candles across 4 timeframes. OANDA allows 5,000 candles per request, so this requires ~148 paginated requests. At a conservative 2 requests/second (well within the 120 req/s limit), the full download takes ~75 seconds.

#### Storage Format

```
data/
  historical/
    XAU_USD/
      M1.parquet       # ~520k rows, ~25MB compressed
      M5.parquet       # ~175k rows, ~8MB compressed
      M15.parquet      # ~35k rows, ~2MB compressed
      H1.parquet       # ~6k rows, <1MB compressed
      metadata.json    # download timestamps, date ranges, row counts
```

Parquet format chosen for:
- Fast columnar reads (training iterates over time windows, not individual candles)
- Compression (~10x vs CSV)
- Schema enforcement (typed columns)
- Native pandas/polars support

#### `metadata.json` Schema

```json
{
  "instrument": "XAU_USD",
  "download_date": "2026-02-20T14:30:00Z",
  "date_range": {
    "start": "2025-02-20T00:00:00Z",
    "end": "2026-02-20T00:00:00Z"
  },
  "timeframes": {
    "M1":  {"rows": 521280, "file": "M1.parquet",  "size_mb": 24.7},
    "M5":  {"rows": 174720, "file": "M5.parquet",  "size_mb": 8.3},
    "M15": {"rows": 34944,  "file": "M15.parquet", "size_mb": 1.7},
    "H1":  {"rows": 5832,   "file": "H1.parquet",  "size_mb": 0.3}
  },
  "pip_value": 0.01,
  "data_quality": {
    "gaps_detected": 12,
    "gaps_filled": 12,
    "weekend_rows_removed": true
  }
}
```

#### Data Quality Pipeline

Raw OANDA data has issues that must be cleaned before training:

1. **Weekend gaps**: Markets close Friday 21:00 UTC → Sunday 22:00 UTC. Remove any candles in this window (OANDA sometimes returns stale prices).
2. **Missing candles**: If a M5 candle is missing (no ticks during that period), forward-fill from the previous candle's close (open=high=low=close=prev_close, volume=0). Mark as synthetic.
3. **Spike detection**: If a single candle's high-low range exceeds 10× the 20-period ATR, flag as a data error or flash crash. Log but don't remove (RL should see extreme events).
4. **Timezone normalization**: All timestamps stored as UTC. Verify OANDA's `"time"` field is ISO 8601 with `Z` suffix.
5. **Volume validation**: OANDA tick volume should be > 0 for non-weekend candles. Flag zero-volume periods (may indicate illiquid conditions).

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Download script** | `app/rl/data_collector.py` | Async function `download_historical(instrument, granularity, start, end, broker) -> pd.DataFrame`. Paginates OANDA's `GET /instruments/{instrument}/candles` endpoint using `from`/`to` params. Handles 5000-candle-per-request limit. Returns DataFrame with columns: `time, open, high, low, close, volume`. |
| 2 | **Data cleaning** | `app/rl/data_collector.py` | `clean_candles(df) -> df`. Weekend removal, gap filling, spike flagging, timezone normalization. |
| 3 | **Storage** | `app/rl/data_collector.py` | `save_to_parquet(df, path)` / `load_from_parquet(path) -> df`. Metadata generation. |
| 4 | **CLI command** | `app/rl/data_collector.py` | Runnable as `python -m app.rl.data_collector --instrument XAU_USD --months 12`. Fetches all 4 timeframes, cleans, saves, reports. |
| 5 | **Data splits** | `app/rl/data_collector.py` | `split_data(df, train_pct=0.7, val_pct=0.15, test_pct=0.15) -> (train_df, val_df, test_df)`. Chronological split (no shuffling — time series must be ordered). Train = first 70% of dates, validation = next 15%, test = final 15%. |
| 6 | **Tests** | `tests/test_rl_data.py` | Data cleaning tests, gap fill tests, split ratio verification, parquet round-trip. |

#### Acceptance Criteria

1. Running `python -m app.rl.data_collector --instrument XAU_USD --months 12` downloads all 4 timeframes to `data/historical/XAU_USD/`.
2. Each parquet file has correct schema: `time (datetime64), open (float64), high (float64), low (float64), close (float64), volume (int64)`.
3. No weekend candles are present in any file.
4. Gap-filled candles are marked with `volume=0`.
5. `metadata.json` is generated with correct row counts and date ranges.
6. Chronological splits maintain temporal ordering (no future data leakage).
7. Download is resumable — if interrupted, re-running skips already-downloaded date ranges.

#### Dependency Changes

- Add `pandas >= 2.0` to `requirements.txt` (data manipulation)
- Add `pyarrow >= 14.0` to `requirements.txt` (parquet backend)

---

### Phase 13.1 — Feature Engineering (State Vector)

#### Purpose

Define and implement the **state representation** — the vector of numbers the RL agent observes at each decision point. This is the single most important design decision in the entire RL system. A state vector that fails to capture the distinction between good and bad setups means the agent literally *cannot* learn, regardless of how sophisticated the neural network or reward function is.

#### Design Principles

1. **Features must be observable at decision time** — no future information leakage. Every feature must be computable from data available *before* the trade decision.
2. **Features must be normalized** — raw prices (e.g., $5000.25) are meaningless across different time periods when gold was at $1800 vs $2500. All features must be scale-invariant.
3. **Features should be uncorrelated where possible** — redundant features (e.g., RSI and Stochastic, which measure the same thing) waste capacity and slow convergence.
4. **Domain knowledge beats raw data** — feeding raw OHLCV to the agent and hoping it learns indicators from scratch wastes millions of timesteps. We pre-compute meaningful indicators using the existing `indicators.py` functions and feed the agent *interpreted* market state.
5. **Cyclical features need special encoding** — hour-of-day 23 and hour 1 are close together but numerically distant. Sine/cosine encoding makes this relationship visible to the neural network.

#### State Vector Specification (27 Features)

```python
@dataclass
class ForgeState:
    """The observation the RL agent receives at each decision point.
    
    All features are normalized to approximately [-1, +1] or [0, 1] range.
    Computed from M5, M1, H1, and M15 candle data plus account state.
    """
    
    # ─── GROUP 1: Trend / Momentum (6 features) ─────────────────────
    
    m5_ema9_distance: float
    # (price - EMA(9)) / ATR(14)
    # Measures how far price is from the pullback zone.
    # Negative = price below EMA (potential buy pullback in uptrend)
    # Positive = price above EMA (potential sell pullback in downtrend)
    # Normalized by ATR so the scale is consistent across volatility regimes.
    # Typical range: [-3.0, +3.0]. Beyond ±2 is overextended.
    
    m5_ema_slope: float
    # (EMA(9)[now] - EMA(9)[5 bars ago]) / ATR(14)
    # Momentum strength — how fast the short-term trend is moving.
    # Steep positive = strong bullish momentum. Near zero = stalling.
    # Normalized by ATR.
    # Typical range: [-2.0, +2.0].
    
    m5_bias_direction: float
    # -1.0 (bearish), 0.0 (flat), +1.0 (bullish)
    # Output of detect_scalp_bias() mapped to numeric.
    # This is the existing strategy's trend gate answer.
    
    m5_consecutive_candles: float
    # Number of consecutive M5 candles in the bias direction / 10
    # Measures momentum persistence. 
    # 8 green candles in a row = 0.8 (strong trending).
    # 2 green candles = 0.2 (just started or choppy).
    # Normalized by /10 to keep in [0, 1] range.
    
    h1_trend_agreement: float
    # +1.0 if H1 EMA(21) > EMA(50) and bias is bullish (agreement)
    # -1.0 if H1 EMA(21) < EMA(50) and bias is bearish (agreement)
    # 0.0 if H1 trend disagrees with M5 bias (conflict — dangerous)
    # Multi-timeframe alignment is one of the strongest edge signals.
    
    h1_ema_slope: float
    # (H1 EMA(21)[now] - H1 EMA(21)[3 bars ago]) / H1 ATR(14)
    # Higher timeframe momentum. Positive = H1 uptrend accelerating.
    # Typical range: [-1.5, +1.5].
    
    # ─── GROUP 2: Volatility (4 features) ───────────────────────────
    
    m5_atr_percentile: float
    # Percentile rank of current M5 ATR(14) within last 100 ATR values.
    # Range: [0.0, 1.0]. 
    # 0.9 = current volatility is in the top 10% of recent history (high vol).
    # 0.1 = very quiet market (low vol — spreads may be wide, moves small).
    # Captures volatility regime without caring about absolute dollar values.
    
    m5_bb_width: float
    # (BB_upper - BB_lower) / price
    # Bollinger Band width as percentage of price.
    # Narrow = squeeze (potential breakout coming).
    # Wide = volatile (big moves, but also big reversals).
    # Typical range: [0.002, 0.02] for Gold.
    
    m5_bb_position: float
    # (price - BB_lower) / (BB_upper - BB_lower)
    # Where price sits within the Bollinger Bands.
    # 0.0 = at lower band, 0.5 = at midpoint, 1.0 = at upper band.
    # >1.0 = above upper band (overextended). <0.0 = below lower band.
    
    vol_expansion_rate: float
    # ATR(14)[now] / ATR(14)[10 bars ago]
    # Is volatility expanding (>1.0) or contracting (<1.0)?
    # Expanding vol + trend = good for scalps.
    # Expanding vol + chop = danger (whipsaws).
    # Typical range: [0.5, 2.0]. Clipped at bounds.
    
    # ─── GROUP 3: RSI / Oscillator (2 features) ─────────────────────
    
    m15_rsi_norm: float
    # RSI(14) on M15 mapped to [-1, +1]:  (RSI - 50) / 50
    # -1.0 = RSI at 0 (maximally oversold)
    # 0.0 = RSI at 50 (neutral)
    # +1.0 = RSI at 100 (maximally overbought)
    # Oversold in a downtrend = potential reversal (be cautious with sells).
    # Oversold in an uptrend = perfect buy dip opportunity.
    
    m5_rsi_norm: float
    # RSI(14) on M5 mapped to [-1, +1]: same normalization.
    # Faster oscillator — captures short-term exhaustion.
    
    # ─── GROUP 4: Candle Structure (4 features) ─────────────────────
    
    m5_body_ratio: float
    # abs(close - open) / (high - low) of the latest M5 candle.
    # 1.0 = full body (no wicks) — strong conviction candle.
    # 0.0 = doji (all wick) — indecision.
    # Range: [0.0, 1.0].
    
    m5_upper_wick_ratio: float
    # (high - max(open, close)) / (high - low)
    # Selling pressure in the candle. High upper wick = sellers pushed back.
    # Range: [0.0, 1.0].
    
    m5_lower_wick_ratio: float
    # (min(open, close) - low) / (high - low)
    # Buying pressure in the candle. High lower wick = buyers pushed back.
    # Range: [0.0, 1.0].
    
    m1_avg_body_ratio: float
    # Average body_ratio of last 3 M1 candles.
    # Confirmation quality — are the last few M1 candles decisive or indecisive?
    # Range: [0.0, 1.0].
    
    # ─── GROUP 5: Session / Time (4 features) ───────────────────────
    
    hour_sin: float
    # sin(2π × hour / 24)
    # Cyclical encoding of hour-of-day.
    # Makes 23:00 and 01:00 close together in feature space.
    # Range: [-1.0, +1.0].
    
    hour_cos: float
    # cos(2π × hour / 24)
    # Second component of cyclical encoding.
    # Together with hour_sin, uniquely identifies any hour.
    # Range: [-1.0, +1.0].
    
    day_of_week: float
    # Day of week / 4.0 (Monday=0, Friday=4)
    # Gold tends to trend on Monday/Tuesday and mean-revert Thursday/Friday.
    # Range: [0.0, 1.0].
    
    minutes_in_session: float
    # Minutes since session open / total session minutes
    # 0.0 = session just opened, 1.0 = session about to close.
    # Late session = higher risk of erratic moves.
    # Range: [0.0, 1.0].
    
    # ─── GROUP 6: Spread / Cost (2 features) ────────────────────────
    
    spread_to_atr: float
    # current_spread / ATR(14)
    # Cost of entry relative to expected move size.
    # High ratio = spread eating into potential profit.
    # 0.02 = spread is 2% of ATR (excellent). 0.15 = 15% (terrible).
    # Typical range: [0.01, 0.20]. Clipped at 0.20.
    
    spread_pips_norm: float
    # current_spread_pips / MAX_SPREAD_PIPS (8.0)
    # How close the spread is to the strategy's hard rejection limit.
    # 0.0 = zero spread (impossible but theoretical best).
    # 1.0 = at the hard limit (about to be rejected anyway).
    # Range: [0.0, 1.0+].
    
    # ─── GROUP 7: Price Structure (3 features) ──────────────────────
    
    dist_to_round_50: float
    # Distance to nearest $50 level / ATR(14)
    # Gold reacts strongly at $X000, $X050, $X100, etc.
    # Near a round number = potential support/resistance/trap.
    # 0.0 = exactly at a round number. >2.0 = far from any.
    # Range: [0.0, ~5.0]. Clipped at 5.0.
    
    dist_to_round_100: float
    # Distance to nearest $100 level / ATR(14)
    # Major psychological levels ($5000, $5100, $5200).
    # Stronger reaction zones than $50 levels.
    # Same normalization.
    
    dist_to_nearest_sr: float
    # Distance to nearest S/R zone (from sr_zones.py) / ATR(14)
    # 0.0 = at a zone. >3.0 = no nearby structural level.
    # Trading at a zone = higher probability of bounce/rejection.
    # Range: [0.0, ~10.0]. Clipped at 10.0.
    
    # ─── GROUP 8: Account / Performance (2 features) ────────────────
    
    current_drawdown: float
    # Current drawdown from peak equity / max_drawdown_pct
    # 0.0 = at equity peak (no drawdown).
    # 1.0 = at the circuit breaker limit.
    # The agent should learn to be more conservative when drawdown is high.
    # Range: [0.0, 1.0+].
    
    recent_trade_performance: float
    # Average R-multiple of last 5 trades, clipped to [-2, +2] then / 2
    # Positive = recent winners (confidence), negative = recent losers.
    # The agent may learn streak-awareness — tighten after losing streaks.
    # Range: [-1.0, +1.0].
```

**Total: 27 features.** All normalized to approximately [-1, +1] or [0, 1]. No raw prices, no absolute dollar values. The agent sees *patterns in relative market structure*, not price levels.

#### Feature Computation Flow

```
At each decision point (when TrendScalpStrategy produces a signal):

1. Gather raw data (already fetched by strategy):
   ├── M5 candles (last 100) → from broker.fetch_candles()
   ├── M1 candles (last 20)  → from broker.fetch_candles()
   ├── H1 candles (last 50)  → from broker.fetch_candles()
   └── M15 candles (last 30) → from broker.fetch_candles()

2. Compute indicators (reuse existing functions):
   ├── calculate_ema(m5, 9)      → EMA(9) series
   ├── calculate_atr(m5, 14)     → M5 ATR
   ├── calculate_atr(h1, 14)     → H1 ATR
   ├── calculate_rsi(m5, 14)     → M5 RSI
   ├── calculate_rsi(m15, 14)    → M15 RSI
   ├── calculate_bollinger(m5, 20, 2.0) → M5 BB
   ├── calculate_ema(h1, 21)     → H1 fast EMA
   ├── calculate_ema(h1, 50)     → H1 slow EMA
   └── detect_sr_zones(h1)       → nearest S/R zone

3. Build state vector:
   └── ForgeStateBuilder.build(m5, m1, h1, m15, indicators, account_state)
       → np.ndarray of shape (27,)
```

#### Why These 27 Features and Not More

- **Group 1 (Trend)**: Captures whether the trade is with or against momentum, at multiple timeframes. The #1 predictor of scalp success.
- **Group 2 (Volatility)**: Captures whether the market environment is suitable for scalping. High ATR + clean trend = good. High ATR + chop = bad.
- **Group 3 (RSI)**: Captures momentum exhaustion. Buying when RSI is already at 75 on M15 (overbought) has lower success than buying at RSI 40 (room to run).
- **Group 4 (Candle Structure)**: Captures the quality of the confirmation pattern. A full-body engulfing candle is more reliable than a doji with a small body.
- **Group 5 (Time)**: Captures session-dependent behaviour without hard-coding session boundaries. The agent learns the gradient from data.
- **Group 6 (Spread)**: Captures transaction cost pressure. A signal with 6-pip spread on Gold is marginal even if everything else looks good.
- **Group 7 (Price Structure)**: Captures psychological and technical levels. The agent learns round-number traps and S/R zone proximity effects.
- **Group 8 (Account)**: Captures risk context. The agent should be more selective when drawdown is high or after a losing streak.

Any fewer features and the agent can't distinguish good from bad setups. Any more and training becomes slow and overfit-prone. 27 is in the sweet spot for a 2-layer policy network with 64 units per layer.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **State dataclass** | `app/rl/features.py` | `ForgeState` with 27 fields + `to_array() -> np.ndarray` method. |
| 2 | **State builder** | `app/rl/features.py` | `ForgeStateBuilder` class with `build(m5_candles, m1_candles, h1_candles, m15_candles, account_state) -> ForgeState`. Calls existing indicator functions, normalizes, clips outliers. |
| 3 | **Normalization utilities** | `app/rl/features.py` | `percentile_rank(values, current)`, `cyclical_encode(value, max_value)`, `clip_feature(value, low, high)`. |
| 4 | **Price structure helpers** | `app/rl/features.py` | `distance_to_round_level(price, multiple) -> float` (e.g., multiple=50 for $50 levels). |
| 5 | **Tests** | `tests/test_rl_features.py` | Feature normalization tests, edge case tests (zero ATR, empty candles), round-trip from candle data to state vector. |

#### Acceptance Criteria

1. `ForgeStateBuilder.build()` produces a `np.ndarray` of shape `(27,)` with dtype `float32`.
2. All features are in their specified ranges (with clipping applied).
3. Cyclical time encoding: `hour_sin` and `hour_cos` for hour 0 and hour 24 produce identical values.
4. `m5_bb_position` is 0.0 when price equals lower band, 1.0 at upper band.
5. `dist_to_round_50` is 0.0 when gold price is exactly $5000.00.
6. Features computed from synthetic ranging data produce different values than features from synthetic trending data (the state vector is discriminative).
7. No NaN or Inf values in any output vector (all edge cases handled).

---

### Phase 13.2 — Gym Environment Design

#### Purpose

Build a `gymnasium`-compatible simulation environment that replays historical Gold candle data, presents state vectors to the RL agent at each decision point, simulates trade execution (entry, SL hit, TP hit, or time exit), and computes rewards. This is the "virtual market" the agent trains in.

#### Environment Specification

```python
class ForgeTradeEnv(gymnasium.Env):
    """Simulated Gold scalping environment for RL training.
    
    Observation space: Box(27,) — the ForgeState vector
    Action space: Discrete(2) — 0=VETO, 1=TAKE
    
    The environment does NOT ask the agent "should I buy or sell?" 
    The existing TrendScalpStrategy already determines direction.
    The agent only decides: "should I allow this trade or block it?"
    This is a BINARY CLASSIFICATION with sequential state dependence.
    
    Episode: One complete pass through a contiguous block of trading
    days (configurable: 1 day, 1 week, or 1 month per episode).
    
    Step: One M5 candle where the rule-based strategy WOULD produce 
    a signal. Non-signal candles are skipped (no decision needed).
    """
```

#### Why Discrete(2) Not Discrete(3)

The existing strategy already determines BUY vs SELL vs NO_SIGNAL. The RL agent is layered **on top** — it only sees timesteps where the strategy produced a signal. Its job is binary: **TAKE** or **VETO**. This dramatically simplifies the learning problem:

- Discrete(3) with BUY/SELL/HOLD would mean the agent must learn **when AND what direction** to trade — a much harder problem requiring millions of timesteps.
- Discrete(2) with TAKE/VETO means the agent only learns **quality assessment** — which setups to let through and which to block. This converges in 100K-500K timesteps.

The agent never contradicts the strategy's direction. It only gates on quality.

#### Episode Structure

```
Episode start:
  ├── Select a random contiguous date range from training data
  │   (e.g., 5 trading days = 1 business week)
  ├── Initialize account state (equity, drawdown=0, trade_history=[])
  └── Scroll through M5 candles chronologically

At each M5 candle:
  ├── Run rule-based signal detection offline:
  │   ├── detect_scalp_bias() on recent M1 data
  │   ├── EMA(9) pullback check
  │   └── Confirmation pattern check
  │
  ├── If NO signal → skip candle (no decision, no reward)
  │
  ├── If SIGNAL exists:
  │   ├── Build state vector from current market data
  │   ├── Present state to agent → agent returns action (0=VETO, 1=TAKE)
  │   │
  │   ├── If VETO (action=0):
  │   │   └── Reward = HOLD_REWARD (small positive, see reward section)
  │   │   └── Advance to next signal
  │   │
  │   └── If TAKE (action=1):
  │       ├── Simulate trade execution:
  │       │   ├── Entry at current M5 close
  │       │   ├── SL from calculate_scalp_sl()
  │       │   ├── TP from calculate_scalp_tp()
  │       │   ├── Scan forward through M1 candles:
  │       │   │   ├── Each M1 candle: check if high >= TP (if LONG)
  │       │   │   │                    or if low <= TP (if SHORT)
  │       │   │   ├── Each M1 candle: check if low <= SL (if LONG)
  │       │   │   │                    or if high >= SL (if SHORT)
  │       │   │   ├── If both SL and TP hit on same candle → pessimistic:
  │       │   │   │   assume SL hit first (conservative bias)
  │       │   │   └── If max_hold_candles exceeded → exit at current close
  │       │   ├── Calculate realized P&L
  │       │   └── Calculate R-multiple: P&L / risk_amount
  │       ├── Reward = f(R_multiple, hold_time, drawdown) (see reward section)
  │       └── Update account state (equity, drawdown, trade_history)
  │
  └── Episode ends when:
      ├── All M5 candles in the date range are exhausted, OR
      ├── Account drawdown exceeds max_drawdown_pct (circuit breaker), OR
      └── Max steps per episode reached (safety cap)
```

#### M1-Resolution Trade Simulation

This is the critical detail that makes the simulation realistic. When the agent takes a trade, we don't just check the next M5 candle for SL/TP — we **scan through every M1 candle** within the trade's lifetime to detect exactly when SL or TP is hit:

```python
def simulate_trade(
    entry_price: float,
    direction: str,       # "buy" or "sell"
    sl: float,
    tp: float,
    m1_candles: list[CandleData],  # M1 candles AFTER entry
    max_hold_minutes: int = 120,   # Force exit after 2 hours
    pip_value: float = 0.01,
) -> TradeOutcome:
    """Simulate a trade through M1 candle data.
    
    Scans each M1 candle to check SL/TP hit.
    Uses pessimistic fill assumption: if both SL and TP could be hit
    on the same candle (high >= TP and low <= SL for a LONG), assume
    SL was hit first. This prevents overly optimistic backtesting.
    
    Returns:
        TradeOutcome(
            exit_price: float,
            exit_reason: "sl_hit" | "tp_hit" | "time_exit",
            hold_minutes: int,
            pnl_pips: float,
            r_multiple: float,
        )
    """
```

**Why M1 and not M5 simulation?** On Gold, a M5 candle can have a $5+ range. An SL set $3 below entry could be hit and then price recovers — all within one M5 candle. If we only checked M5, we'd miss the SL hit and show a winning trade that would have been a loss in reality. M1 simulation catches these intra-candle moves with much higher fidelity.

**Pessimistic fill assumption**: When a single M1 candle's range covers both SL and TP (extremely volatile candle), we assume SL was hit first. This creates a conservative training signal — the agent learns to avoid setups where SL is close enough to be hit even in winning scenarios. This prevents the agent from learning to take trades in extremely volatile conditions where the outcome is essentially random.

#### Trade Duration Logic

| Scenario | Exit Logic |
|----------|-----------|
| TP hit before SL | Exit at TP price. `exit_reason = "tp_hit"`. |
| SL hit before TP | Exit at SL price. `exit_reason = "sl_hit"`. |
| Both on same M1 candle | Assume SL hit first (pessimistic). `exit_reason = "sl_hit"`. |
| Neither hit after `max_hold_minutes` | Exit at current M1 close. `exit_reason = "time_exit"`. |
| Weekend gap during trade | Exit at Friday's last M1 close. `exit_reason = "weekend_close"`. |

The `max_hold_minutes = 120` (2 hours) reflects the scalping strategy's intent — these are short-duration trades. Holding for 4+ hours means the setup failed. The R-multiple for time exits is typically near zero (small loss or gain) which trains the agent that marginal setups are not worth it.

#### Environment Configuration

```python
@dataclass
class EnvConfig:
    """Configuration for the Gym environment."""
    
    instrument: str = "XAU_USD"
    pip_value: float = 0.01
    
    # Episode configuration
    episode_length_days: int = 5        # 1 trading week per episode
    max_steps_per_episode: int = 200    # Safety cap on decisions per episode
    
    # Trade simulation
    max_hold_minutes: int = 120         # Force-close after 2 hours
    risk_per_trade_pct: float = 2.0     # Matches live stream config
    initial_equity: float = 10_000.0    # Starting equity per episode
    max_drawdown_pct: float = 10.0      # Episode ends at circuit breaker
    
    # SL/TP (mirrors live strategy)
    rr_ratio: float = 1.5              # Fixed R:R for TP calculation
    min_sl_pips: float = 15.0          # Reject if SL < 15 pips
    max_sl_pips: float = 100.0         # Reject if SL > 100 pips
    
    # Signal generation (offline rule-based)
    bias_lookback: int = 15
    bias_threshold: float = 0.6
    ema_pullback_period: int = 9
    pullback_proximity_pct: float = 0.006  # 0.6% of price
    
    # Feature computation
    atr_period: int = 14
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
```

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Environment class** | `app/rl/environment.py` | `ForgeTradeEnv(gymnasium.Env)` with `reset()`, `step()`, `_get_obs()`, `_simulate_trade()`, `_check_signal()`. |
| 2 | **Trade simulator** | `app/rl/environment.py` | `simulate_trade()` function — M1-resolution SL/TP scanning. |
| 3 | **Offline signal detector** | `app/rl/environment.py` | `_check_signal()` — runs `detect_scalp_bias()` + `evaluate_scalp_entry()` on historical data without broker calls. |
| 4 | **Episode manager** | `app/rl/environment.py` | Handles date range selection, candle alignment across timeframes, and episode termination. |
| 5 | **Environment config** | `app/rl/environment.py` | `EnvConfig` dataclass with defaults matching live strategy. |
| 6 | **Tests** | `tests/test_rl_env.py` | Environment reset/step cycle, trade simulation correctness, episode termination conditions, observation space shape verification. |

#### Acceptance Criteria

1. `env = ForgeTradeEnv(data, config)` creates valid Gymnasium environment.
2. `env.observation_space.shape == (27,)` and `env.action_space.n == 2`.
3. `env.reset()` returns a valid observation and info dict.
4. `env.step(1)` (TAKE) simulates a trade and returns correct reward.
5. `env.step(0)` (VETO) returns hold reward and advances to next signal.
6. Trade simulation on known data produces correct P&L (verified against manual calculation).
7. Pessimistic fill: when M1 candle spans both SL and TP, trade is recorded as SL loss.
8. Episode ends at `max_drawdown_pct` with `terminated=True`.
9. Episode ends at data exhaustion with `truncated=True`.
10. `check_env(env)` from `stable_baselines3.common.env_checker` passes.

#### Dependency Changes

- Add `gymnasium >= 0.29` to `requirements.txt`

---

### Phase 13.3 — Reward Shaping

#### Purpose

Define the reward function — the signal that tells the agent what "good" means. This is the **most critical design decision** in the entire system. A flawed reward function produces an agent that games the metric instead of learning genuine trade quality assessment.

#### Reward Function Design

The reward function has four components, carefully weighted to produce the right incentive structure:

```python
def calculate_reward(
    action: int,                    # 0=VETO, 1=TAKE
    trade_outcome: TradeOutcome | None,  # None if VETO
    account_state: AccountState,
    config: RewardConfig,
) -> float:
    """Calculate the shaped reward for a single step.
    
    Returns a scalar reward consumed by the PPO algorithm.
    """
```

##### Component 1: Trade Outcome Reward (Core)

```python
if action == 0:  # VETO
    # Reward for not trading — what WOULD have happened?
    # Simulate the trade anyway (counterfactual) to judge the veto
    if counterfactual_outcome.r_multiple < 0:
        # Correctly vetoed a losing trade
        reward_core = CORRECT_VETO_REWARD  # +0.3
    else:
        # Incorrectly vetoed a winning trade  
        reward_core = MISSED_WINNER_PENALTY  # -0.15
        # Note: penalty for missing winners is HALF the reward for 
        # avoiding losers. This creates asymmetry: the agent learns
        # that avoiding losses is more important than catching winners.
        # This produces a conservative, capital-preserving agent.

elif action == 1:  # TAKE
    r_multiple = trade_outcome.r_multiple
    reward_core = r_multiple  # Direct R-multiple: +1.5 for TP hit, -1.0 for SL hit
```

**Why counterfactual rewards for VETO?** Without this, the agent receives a flat reward for vetoing (e.g., +0.001) regardless of whether the veto was correct. It can never learn *which* vetoes were good. By simulating what would have happened, we give it feedback on its judgment quality.

**Why asymmetric veto rewards?** In trading, a dollar saved is worth more than a dollar earned (losses compound harder than gains due to drawdown math). An agent that vetoes 30% of trades but avoids 80% of the worst losers is more valuable than one that catches every winner but also lets through every loser. The 2:1 asymmetry (0.3 for correct veto vs 0.15 penalty for missed winner) encodes this principle.

##### Component 2: Hold Duration Penalty

```python
if action == 1 and trade_outcome is not None:
    # Penalize trades that take too long — scalps should resolve quickly
    hold_hours = trade_outcome.hold_minutes / 60.0
    
    if hold_hours <= 0.5:
        # Under 30 min — no penalty (ideal scalp duration)
        duration_penalty = 0.0
    elif hold_hours <= 1.0:
        # 30-60 min — mild penalty
        duration_penalty = -0.05
    elif hold_hours <= 2.0:
        # 1-2 hours — moderate penalty
        duration_penalty = -0.15
    else:
        # Forced time exit (>2 hours) — significant penalty
        duration_penalty = -0.3
```

**Rationale**: Scalps that take 2+ hours to resolve are not scalps — they're positions that never moved. Even if they eventually win, the capital was locked up unproductively. The agent should learn to avoid setups that tend to stall.

##### Component 3: Drawdown Contribution Cost

```python
if action == 1 and trade_outcome is not None and trade_outcome.pnl < 0:
    # Additional cost when the loss pushes drawdown deeper
    new_dd = account_state.drawdown_after_trade
    old_dd = account_state.drawdown_before_trade
    dd_increase = max(0, new_dd - old_dd)
    
    # Scale: losing 2% drawdown on top of existing drawdown is worse
    # than losing 2% from equity peak
    if old_dd > 0.05:  # Already in 5%+ drawdown
        drawdown_penalty = -dd_increase * 3.0  # 3× amplified
    elif old_dd > 0.03:
        drawdown_penalty = -dd_increase * 2.0  # 2× amplified
    else:
        drawdown_penalty = -dd_increase * 1.0  # Normal cost
```

**Rationale**: This creates a **state-dependent risk preference**. When the account is healthy (drawdown < 3%), taking calculated risks is fine — losses are just losses. When the account is already in drawdown (> 5%), additional losses are amplified because they push toward the circuit breaker and compound recovery difficulty. The agent learns to **tighten its filter during losing periods** — exactly what a human trader should do.

##### Component 4: Streak Awareness Bonus

```python
# Bonus for building winning streaks, penalty for extending losing streaks
recent_trades = account_state.last_5_trades  # list of R-multiples

if action == 1:
    if len(recent_trades) >= 3:
        last_3_wins = sum(1 for r in recent_trades[-3:] if r > 0)
        
        if last_3_wins == 3 and trade_outcome.r_multiple > 0:
            # Extended a win streak — small bonus for consistency
            streak_bonus = +0.1
        elif last_3_wins == 0 and trade_outcome.r_multiple < 0:
            # Extended a losing streak — extra penalty for not tightening up
            streak_bonus = -0.15
        else:
            streak_bonus = 0.0
    else:
        streak_bonus = 0.0
```

**Rationale**: Losing streaks are real. Even with 66% win rate, 3 losses in a row happen ~3.7% of the time. Professional traders reduce size or pause after 3 consecutive losses. This reward component encodes that wisdom — the agent gets extra punishment for letting a 4th loss through after 3 losses.

##### Combined Reward

```python
total_reward = (
    reward_core           # [-1.0, +1.5] for TAKE; [-0.15, +0.3] for VETO
    + duration_penalty    # [-0.3, 0.0]
    + drawdown_penalty    # [-0.06, 0.0] typical
    + streak_bonus        # [-0.15, +0.1]
)

# Final clipping to prevent extreme rewards from destabilizing training
return np.clip(total_reward, -2.0, +2.0)
```

#### Reward Configuration

```python
@dataclass
class RewardConfig:
    """Tunable reward parameters."""
    
    correct_veto_reward: float = 0.3
    missed_winner_penalty: float = -0.15
    
    # Duration thresholds (minutes)
    ideal_hold_max: int = 30
    moderate_hold_max: int = 60
    long_hold_max: int = 120
    
    # Duration penalties
    moderate_hold_penalty: float = -0.05
    long_hold_penalty: float = -0.15
    time_exit_penalty: float = -0.3
    
    # Drawdown amplification thresholds
    dd_warning_threshold: float = 0.03  # 3%
    dd_danger_threshold: float = 0.05   # 5%
    dd_warning_multiplier: float = 2.0
    dd_danger_multiplier: float = 3.0
    
    # Streak
    losing_streak_extra_penalty: float = -0.15
    winning_streak_bonus: float = 0.1
    streak_lookback: int = 3
    
    # Reward clipping
    reward_min: float = -2.0
    reward_max: float = 2.0
```

#### Reward Distribution Analysis (Expected)

Given a hypothetical agent with 66% take rate and 70% accuracy on taken trades:

| Scenario | Frequency | Reward | Contribution |
|----------|-----------|--------|-------------|
| Correct take (TP hit, <30min) | ~35% | +1.5 | +0.525 |
| Correct take (TP hit, 30-60min) | ~10% | +1.45 | +0.145 |
| Incorrect take (SL hit, <30min) | ~12% | -1.0 | -0.120 |
| Incorrect take (SL hit, 30-60min) | ~5% | -1.05 | -0.053 |
| Time exit (near zero P&L) | ~5% | -0.30 | -0.015 |
| Correct veto (avoided loser) | ~20% | +0.3 | +0.060 |
| Incorrect veto (missed winner) | ~13% | -0.15 | -0.020 |
| **Expected reward per step** | | | **≈ +0.52** |

A positive expected reward per step means the agent is incentivized to be moderately selective — taking most signals but vetoing the bottom ~33% by quality.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Reward function** | `app/rl/rewards.py` | `calculate_reward()` with all 4 components. |
| 2 | **Reward config** | `app/rl/rewards.py` | `RewardConfig` dataclass with tunable params. |
| 3 | **Counterfactual simulator** | `app/rl/rewards.py` | `compute_counterfactual(entry, direction, sl, tp, m1_candles) -> TradeOutcome`. Used for scoring VETOs. |
| 4 | **Account state tracker** | `app/rl/rewards.py` | `AccountState` class tracking equity, drawdown, trade history for reward computation. |
| 5 | **Tests** | `tests/test_rl_rewards.py` | Correct veto scoring, duration penalties, drawdown amplification at thresholds, streak detection, reward clipping, counterfactual accuracy. |

#### Acceptance Criteria

1. `calculate_reward(action=1, outcome=win_1_5R, ...)` returns approximately +1.5 (core reward, no penalties).
2. `calculate_reward(action=1, outcome=sl_hit, ...)` returns approximately -1.0 (core reward, no extras).
3. `calculate_reward(action=0, counterfactual=loser)` returns +0.3 (correct veto).
4. `calculate_reward(action=0, counterfactual=winner)` returns -0.15 (missed winner).
5. Duration penalty: 90-minute trade gets -0.15 additional penalty.
6. Drawdown amplification: losing trade during 6% drawdown gets 3× drawdown contribution penalty.
7. Losing streak: 4th consecutive loss gets extra -0.15 penalty.
8. Reward is always clipped to [-2.0, +2.0].
9. Counterfactual simulation produces identical outcome to `simulate_trade()` with same inputs.

---

### Phase 13.4 — Neural Network Architecture

#### Purpose

Define the policy and value network architecture used by the PPO algorithm. The network maps the 27-feature state vector to action probabilities (policy/actor) and state value estimates (critic). The architecture must be expressive enough to capture non-linear feature interactions (e.g., "high ATR + late session + near round number = bad") while small enough to avoid overfitting on 12 months of Gold data.

#### Architecture: Shared Feature Extractor + Dual Head

```
Input: ForgeState (27 features)
         │
         ▼
┌─────────────────────────────────┐
│   Shared Feature Extractor      │
│                                 │
│   Linear(27 → 128) + LayerNorm │
│   + LeakyReLU(0.01)            │
│   + Dropout(0.1)               │
│                                 │
│   Linear(128 → 64) + LayerNorm │
│   + LeakyReLU(0.01)            │
│   + Dropout(0.1)               │
│                                 │
│   Linear(64 → 64) + LayerNorm  │
│   + LeakyReLU(0.01)            │
│                                 │
└───────────┬─────────────────────┘
            │
     ┌──────┴──────┐
     ▼              ▼
┌─────────┐   ┌─────────┐
│  Policy  │   │  Value  │
│  (Actor) │   │ (Critic)│
│          │   │         │
│ L(64→32) │   │ L(64→32)│
│ + LReLU  │   │ + LReLU │
│ L(32→2)  │   │ L(32→1) │
│ + Softmax│   │         │
│          │   │         │
│ P(VETO)  │   │  V(s)   │
│ P(TAKE)  │   │         │
└─────────┘   └─────────┘
```

#### Design Decisions Explained

**Why shared feature extractor?** The policy ("what to do") and value ("how good is this state") both need to understand the market state. Sharing the first 3 layers means they learn a common representation, which:
- Reduces total parameters (fewer weights to overfit)
- Provides implicit regularization (policy and value gradients both flow through shared layers)
- Converges faster (shared features are trained by both losses)

**Why 3 layers (128-64-64)?** 
- Layer 1 (27→128): Expands the feature space to learn pairwise interactions. With 27 inputs, there are 351 possible pairwise interactions. 128 neurons can capture the most important ones.
- Layer 2 (128→64): Compresses to identify the key latent factors. Most market states can be characterized by roughly 10-20 latent variables (trend strength, volatility regime, session quality, etc.). 64 is generous enough to capture these without redundancy.
- Layer 3 (64→64): Adds representational depth for higher-order interactions (e.g., "trend strong + volatility expanding + session good" vs any two of those three). Two layers can't learn 3-way interactions; three layers can.
- Deeper (4+ layers) would overfit on this dataset size. The generalization-depth tradeoff favors shallow but wide for RL on limited financial data.

**Why LayerNorm (not BatchNorm)?**
- BatchNorm depends on batch statistics that shift during training. In RL, the data distribution changes as the policy improves (non-stationary). LayerNorm normalizes per-sample, independent of batch, which is more stable for RL.

**Why LeakyReLU (not ReLU)?**
- ReLU can cause "dead neurons" — neurons that output zero for all inputs and never recover. With only ~50K gradient updates (typical PPO training), losing neurons is expensive. LeakyReLU with α=0.01 maintains gradient flow even for negative inputs.

**Why Dropout(0.1)?**
- Light regularization to reduce overfitting. 0.1 is conservative — only 10% of neurons dropped per forward pass during training. Too much dropout (e.g., 0.3) destabilizes PPO because the policy distribution jitters between forward passes.

**Why separate policy and value heads?**
- PPO needs both. The policy head outputs action probabilities. The value head estimates how much total future reward to expect from this state. They share features but need different final transformations — the policy must output a probability distribution (softmax), while the value is a scalar (unbounded).

#### Network Size Analysis

| Component | Parameters |
|-----------|-----------|
| Shared Layer 1: 27×128 + 128 bias + 128 LayerNorm | 3,712 |
| Shared Layer 2: 128×64 + 64 bias + 64 LayerNorm | 8,384 |
| Shared Layer 3: 64×64 + 64 bias + 64 LayerNorm | 4,288 |
| Policy Layer 1: 64×32 + 32 bias | 2,080 |
| Policy Layer 2: 32×2 + 2 bias | 66 |
| Value Layer 1: 64×32 + 32 bias | 2,080 |
| Value Layer 2: 32×1 + 1 bias | 33 |
| **Total** | **~20,643 parameters** |

~20K parameters is tiny by modern ML standards. This is deliberate — with ~50K-100K training samples, a model with 20K parameters has a healthy data-to-parameter ratio of ~3-5:1. A model with 1M parameters would have 0.05:1 — guaranteed overfitting.

For comparison:
- GPT-2: 1.5 billion parameters
- A typical image classifier: 25 million parameters
- ForgeAgent: 20K parameters

Simple problems need simple models. "Should I take this trade?" is a simple (but nuanced) binary question.

#### PPO Hyperparameters

```python
PPO_CONFIG = {
    # Core PPO
    "learning_rate": 3e-4,           # Standard for PPO. Adam optimizer.
    "n_steps": 2048,                 # Steps per rollout buffer collection.
                                     # With ~15 signals/day × 5 days = 75 steps/episode,
                                     # this means ~27 episodes per rollout.
    "batch_size": 64,                # Mini-batch size for SGD updates.
    "n_epochs": 10,                  # PPO epochs per rollout (how many times
                                     # we iterate over the collected data).
    "gamma": 0.99,                   # Discount factor for future rewards.
                                     # 0.99 means rewards 100 steps ahead are
                                     # worth ~37% of immediate rewards.
                                     # For trading: a good veto now contributes
                                     # to better account state for future trades.
    "gae_lambda": 0.95,             # GAE lambda for advantage estimation.
                                     # 0.95 balances bias/variance in advantage
                                     # estimation. Standard value.
    "clip_range": 0.2,              # PPO clipping parameter. Prevents the
                                     # policy from changing too drastically
                                     # in one update. Standard value.
    "ent_coef": 0.01,               # Entropy coefficient. Encourages exploration.
                                     # 0.01 means 1% of the loss comes from
                                     # entropy — keeps the agent from collapsing
                                     # to always-TAKE or always-VETO too early.
    "vf_coef": 0.5,                 # Value function coefficient in the combined
                                     # loss. Standard.
    "max_grad_norm": 0.5,           # Gradient clipping for stability.
    
    # Network
    "policy_kwargs": {
        "net_arch": {
            "pi": [32],             # Policy head hidden layer(s) after shared
            "vf": [32],             # Value head hidden layer(s) after shared
        },
        "share_features_extractor": True,
        "features_extractor_kwargs": {
            "net_arch": [128, 64, 64],
        },
        "activation_fn": "LeakyReLU",
    },
    
    # Training
    "total_timesteps": 500_000,     # Total agent decisions during training.
                                     # At ~75 signals/episode (5-day episodes),
                                     # this is ~6,667 episodes = ~133 passes
                                     # through 1 year of data.
    "seed": 42,                     # Reproducibility.
}
```

#### Why These Hyperparameters

| Parameter | Value | Why |
|-----------|-------|-----|
| `learning_rate: 3e-4` | Adam default for PPO. Too high → unstable. Too low → slow convergence. 3e-4 is the "just right" starting point validated across thousands of PPO papers. |
| `n_steps: 2048` | Number of transitions collected before each policy update. Must be large enough to include diverse market states. 2048 ≈ 27 five-day episodes — covers multiple volatility regimes. |
| `batch_size: 64` | Mini-batch for SGD. 64 is standard. Smaller → noisier gradients. Larger → fewer update steps per rollout. |
| `n_epochs: 10` | How many times PPO iterates over each batch of collected data. 10 is standard. More → better sample efficiency but risks overfitting to the batch. |
| `gamma: 0.99` | Discount factor. 0.99 is standard for episodic tasks. The agent cares about total episode reward, not just immediate. |
| `clip_range: 0.2` | PPO's core mechanism — prevents large policy updates. 0.2 means the probability ratios are clipped to [0.8, 1.2]. Standard value from the original PPO paper. |
| `ent_coef: 0.01` | Exploration bonus. 0.01 keeps the agent exploring (not always picking the same action) while being small enough not to overwhelm the main objective. |
| `total_timesteps: 500K` | Conservative. PPO on simple discrete problems often converges in 100K-200K. 500K provides margin. Training can be stopped early if validation performance plateaus. |

#### Custom Feature Extractor (Stable Baselines3 Integration)

Stable Baselines3 supports custom feature extractors via subclassing:

```python
from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

class ForgeFeatureExtractor(BaseFeaturesExtractor):
    """Custom 3-layer shared feature extractor for ForgeAgent.
    
    Replaces SB3's default MLP extractor with our LayerNorm + 
    LeakyReLU + Dropout architecture.
    """
    
    def __init__(self, observation_space, features_dim=64):
        super().__init__(observation_space, features_dim)
        
        self.net = nn.Sequential(
            nn.Linear(27, 128),
            nn.LayerNorm(128),
            nn.LeakyReLU(0.01),
            nn.Dropout(0.1),
            
            nn.Linear(128, 64),
            nn.LayerNorm(64),
            nn.LeakyReLU(0.01),
            nn.Dropout(0.1),
            
            nn.Linear(64, 64),
            nn.LayerNorm(64),
            nn.LeakyReLU(0.01),
        )
    
    def forward(self, observations):
        return self.net(observations)
```

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Feature extractor** | `app/rl/network.py` | `ForgeFeatureExtractor(BaseFeaturesExtractor)` — 3-layer shared encoder. |
| 2 | **PPO config** | `app/rl/network.py` | `PPO_CONFIG` dict with all hyperparameters. `build_agent(env) -> PPO` factory function. |
| 3 | **Tests** | `tests/test_rl_network.py` | Feature extractor forward pass shape test, parameter count verification, gradient flow test (no dead neurons). |

#### Acceptance Criteria

1. `ForgeFeatureExtractor` accepts `(batch, 27)` input and produces `(batch, 64)` output.
2. Total parameter count is within 10% of 20,643.
3. Forward pass through the full network (extractor → policy head) produces valid probability distribution (sums to 1.0).
4. Forward pass through the full network (extractor → value head) produces single scalar.
5. No NaN gradients after 100 random forward-backward passes.
6. `build_agent(env)` returns a valid `PPO` instance that can call `.predict()` and `.learn()`.

#### Dependency Changes

- Add `stable-baselines3 >= 2.0` to `requirements.txt` (PPO implementation + SB3 utilities)
- Add `torch >= 2.0` to `requirements.txt` (neural network backend — installed automatically with SB3)
- Add `tensorboard >= 2.14` to `requirements.txt` (training metrics logging)

---

### Phase 13.5 — Training Pipeline

#### Purpose

Orchestrate the full training loop: load data → create environments → train agent → save checkpoints → log metrics. This is the glue connecting Phases 13.0–13.4 into a runnable training workflow.

#### Training Flow

```
python -m app.rl.train --instrument XAU_USD --config rl_config.json

1. Load historical data from data/historical/XAU_USD/
   ├── Load M1, M5, M15, H1 parquet files
   ├── Apply chronological split (70% train, 15% val, 15% test)
   └── Validate data quality (no gaps, correct date ranges)

2. Create training environment
   ├── ForgeTradeEnv(train_data, env_config)
   ├── Wrap with gymnasium wrappers:
   │   ├── NormalizeReward (stabilizes reward scale during training)
   │   ├── TimeLimit (max_steps per episode)
   │   └── Monitor (logs episode stats)
   └── Optionally: SubprocVecEnv with N=4 parallel environments
       (4× faster training by collecting 4 episodes simultaneously)

3. Create validation environment
   ├── ForgeTradeEnv(val_data, env_config)
   └── NOT wrapped with NormalizeReward (raw rewards for evaluation)

4. Build PPO agent
   ├── PPO("MlpPolicy", env, **PPO_CONFIG)
   ├── Custom ForgeFeatureExtractor
   └── Set seed for reproducibility

5. Training loop (with early stopping)
   ├── For each training iteration (every n_steps):
   │   ├── Collect 2048 transitions from training env
   │   ├── Perform 10 epochs of PPO updates
   │   ├── Log to TensorBoard:
   │   │   ├── policy_loss, value_loss, entropy
   │   │   ├── mean_reward, episode_length
   │   │   ├── explained_variance
   │   │   └── custom: take_rate, win_rate, avg_r_multiple
   │   │
   │   ├── Every 10 iterations: evaluate on validation env
   │   │   ├── Run 20 episodes on validation data
   │   │   ├── Calculate validation metrics:
   │   │   │   ├── mean_reward, median_reward
   │   │   │   ├── win_rate (of taken trades)
   │   │   │   ├── take_rate (% of signals taken)
   │   │   │   ├── profit_factor
   │   │   │   ├── max_drawdown
   │   │   │   └── sharpe_ratio (on episode returns)
   │   │   ├── Save if best validation reward so far
   │   │   └── Early stopping: if validation reward hasn't improved
   │   │       for 50 iterations → stop training
   │   │
   │   └── Save checkpoint every 50 iterations:
   │       └── models/forge_agent/checkpoint_{iteration}.zip
   │
   └── Final save: models/forge_agent/best_model.zip

6. Post-training report
   ├── Print training summary:
   │   ├── Total timesteps trained
   │   ├── Best validation reward and iteration
   │   ├── Training time
   │   └── Final take rate and win rate
   └── Save report to models/forge_agent/training_report.json
```

#### Parallel Training Environments

Training with a single environment is slow because PPO must wait for each episode to complete before updating. Using `SubprocVecEnv` with 4 parallel environments means 4 episodes run simultaneously in separate processes:

```python
from stable_baselines3.common.vec_env import SubprocVecEnv

def make_env(data, config, seed):
    def _init():
        env = ForgeTradeEnv(data, config)
        env.reset(seed=seed)
        return env
    return _init

# 4 parallel environments with different random seeds
vec_env = SubprocVecEnv([
    make_env(train_data, env_config, seed=42 + i) 
    for i in range(4)
])
```

Each environment selects different random date ranges for episodes, so the agent sees diverse market conditions simultaneously. This doesn't change the algorithm — it just provides 4× more data per collection cycle.

#### Noise Injection (Anti-Overfitting)

During training, apply small random perturbations to the state vector to prevent the agent from memorizing specific numerical patterns:

```python
class NoisyObservationWrapper(gymnasium.ObservationWrapper):
    """Adds Gaussian noise to observations during training.
    
    Prevents the agent from memorizing exact feature values.
    At test time, noise is disabled.
    """
    
    def __init__(self, env, noise_std=0.02):
        super().__init__(env)
        self.noise_std = noise_std
    
    def observation(self, obs):
        if self.training:
            noise = np.random.normal(0, self.noise_std, size=obs.shape)
            return (obs + noise).astype(np.float32)
        return obs
```

`noise_std=0.02` means each feature is perturbed by ±2% of its standard deviation. This is enough to break memorization while preserving the signal.

#### TensorBoard Logging

Custom metrics logged each iteration:

```python
class ForgeTrainingCallback(BaseCallback):
    """Logs trading-specific metrics to TensorBoard."""
    
    def _on_step(self):
        # Extract from info dicts
        infos = self.locals.get("infos", [])
        for info in infos:
            if "trade_result" in info:
                self.logger.record("forge/take_rate", info["take_rate"])
                self.logger.record("forge/win_rate", info["win_rate"])
                self.logger.record("forge/avg_r_multiple", info["avg_r"])
                self.logger.record("forge/max_drawdown", info["max_dd"])
                self.logger.record("forge/profit_factor", info["pf"])
        return True
```

#### Directory Structure

```
models/
  forge_agent/
    best_model.zip           # Best validation model (deployed to live)
    final_model.zip          # Model at end of training
    checkpoint_050.zip       # Periodic checkpoints
    checkpoint_100.zip
    ...
    training_report.json     # Performance summary
    config.json              # EnvConfig + RewardConfig + PPO_CONFIG used
    tensorboard/
      events.out.tfevents.*  # TensorBoard logs
```

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Training script** | `app/rl/train.py` | CLI entry point. Loads data, creates envs, builds agent, runs training loop with validation and early stopping. |
| 2 | **Evaluation function** | `app/rl/evaluate.py` | `evaluate_agent(model, val_env, n_episodes=20) -> dict`. Runs episodes, computes win_rate, take_rate, profit_factor, sharpe, max_dd. |
| 3 | **Training callback** | `app/rl/train.py` | `ForgeTrainingCallback(BaseCallback)` — logs custom metrics. |
| 4 | **Noise wrapper** | `app/rl/environment.py` | `NoisyObservationWrapper` for training-time noise injection. |
| 5 | **Config serialization** | `app/rl/train.py` | Save all configs (env, reward, PPO) to `config.json` alongside model for reproducibility. |
| 6 | **Tests** | `tests/test_rl_train.py` | Training runs for 100 timesteps without error. Model saves and loads correctly. Evaluation produces valid metrics dict. |

#### Acceptance Criteria

1. `python -m app.rl.train --instrument XAU_USD --timesteps 1000` completes without errors (quick smoke test).
2. Model saves to `models/forge_agent/best_model.zip` in SB3 format.
3. Saved model loads and produces valid predictions: `model.predict(obs)` returns action in {0, 1}.
4. TensorBoard logs are generated and viewable (`tensorboard --logdir models/forge_agent/tensorboard/`).
5. Validation evaluation runs 20 episodes and returns dict with all expected metrics.
6. Early stopping fires when validation reward stagnates (testable with a mocked non-improving env).
7. Training report JSON includes all key metrics and the config used.
8. `SubprocVecEnv` with 4 environments runs without deadlocks or crashes.
9. Noise wrapper adds noise during training but not during evaluation.

#### Dependency Changes

None beyond Phase 13.4 (SB3 and PyTorch already added).

---

### Phase 13.6 — Evaluation & Walk-Forward Validation

#### Purpose

Rigorously test the trained agent on unseen data using multiple evaluation protocols. The agent must pass quantitative thresholds before it's allowed anywhere near live trading. This phase is the **quality gate** — it separates a genuinely useful model from an overfitted artifact.

#### Evaluation Protocols

##### Protocol 1: Holdout Test Set

Run the agent on the 15% holdout test data (last ~7 weeks of the 12-month dataset). This data was never seen during training or validation.

```
Test metrics (MUST PASS ALL):
  ├── Win rate of taken trades ≥ 60%
  ├── Take rate (signals taken vs total) between 40% and 85%
  │   (too low = vetoing everything, too high = not filtering)
  ├── Profit factor ≥ 1.3 (gross profit / gross loss)
  ├── Max drawdown < 8%
  ├── Average R-multiple of taken trades > 0.0 (net positive)
  └── Sharpe ratio > 0.5 (annualized, if applicable to the period)
```

**Why these thresholds?** They're deliberately achievable but meaningful:
- 60% win rate: The unfiltered strategy runs ~55-60%. The RL filter should improve this by vetoing weak setups. 60% is the minimum improvement to justify the complexity.
- 40-85% take rate: An agent that takes <40% of signals is too conservative — it's locked out of too many valid trades. An agent that takes >85% isn't filtering meaningfully.
- Profit factor 1.3: For every $1 lost, the agent makes $1.30. Sustainable edge.
- Max DD <8%: Below the 10% circuit breaker. The agent should never push near the breaker on test data.

##### Protocol 2: Walk-Forward Validation

The gold standard for time-series models. Instead of one train/test split, perform multiple overlapping splits:

```
Split 1: Train on months 1-6,  validate on month 7
Split 2: Train on months 2-7,  validate on month 8
Split 3: Train on months 3-8,  validate on month 9
Split 4: Train on months 4-9,  validate on month 10
Split 5: Train on months 5-10, validate on month 11
Split 6: Train on months 6-11, validate on month 12
```

6 splits, each with 6 months of training and 1 month of out-of-sample testing. The agent must pass the threshold criteria on **at least 4 of 6 splits** (67% consistency). This tests whether the learned patterns generalize across different market regimes.

```
Walk-forward criteria:
  ├── Pass holdout thresholds on ≥ 4/6 splits
  ├── No split has max drawdown > 12%
  ├── Average win rate across all splits ≥ 58%
  └── Variance of win rate across splits < 15% (consistency)
```

**Interpretation**: If the agent passes on only 2-3 splits, it probably learned regime-specific patterns that don't generalize. If it passes on 5-6, it's robust.

##### Protocol 3: Regime-Specific Testing

Manually tag historical periods by regime and test each:

```
Regime tagging:
  ├── Trending up    (Gold rallying for 2+ weeks, ADX > 30)
  ├── Trending down  (Gold falling for 2+ weeks, ADX > 30)
  ├── Ranging        (ADX < 20 for 2+ weeks)
  ├── High volatility (ATR > 1.5× 60-day average)
  └── Low volatility  (ATR < 0.5× 60-day average)

Expected behavior:
  ├── Trending: high take rate (>70%), good win rate (65%+)
  ├── Ranging: low take rate (<50%), moderate win rate (55%+)
  ├── High vol: moderate take rate (50-65%), win rate varies
  └── Low vol: very low take rate (<40%) — agent should sit out
```

**This doesn't have hard pass/fail thresholds** — it's diagnostic. If the agent takes 80% of signals during ranging markets (when the scalp strategy doesn't work well), that's concerning even if overall metrics are fine. This analysis guides manual review.

##### Protocol 4: Comparison vs. Unfiltered Strategy

Run the same test data through:
- **Baseline**: All signals taken (no RL filter)
- **Filtered**: Signals filtered by ForgeAgent

```
Comparison metrics:
  ├── Win rate: filtered ≥ baseline + 5%
  ├── Profit factor: filtered ≥ baseline × 1.15
  ├── Total P&L: filtered ≥ baseline (or within 5% — the filter
  │   may slightly reduce total profit by missing some winners,
  │   but should SIGNIFICANTLY reduce drawdown)
  └── Max drawdown: filtered ≤ baseline × 0.75 (25% less drawdown)
```

The most important comparison is **max drawdown reduction**. The RL filter's primary value is capital preservation — avoiding the -$3,124 trades. Even if total profit is similar, reducing drawdown by 25% is transformative for real-money trading psychology and compounding.

#### Evaluation Report

```json
{
  "model_path": "models/forge_agent/best_model.zip",
  "evaluation_date": "2026-03-15T10:00:00Z",
  "training_config": { "...": "..." },
  
  "holdout_test": {
    "win_rate": 0.67,
    "take_rate": 0.63,
    "profit_factor": 1.52,
    "max_drawdown": 0.054,
    "avg_r_multiple": 0.31,
    "sharpe_ratio": 0.82,
    "total_trades_taken": 94,
    "total_signals_seen": 149,
    "passed": true
  },
  
  "walk_forward": {
    "splits": [
      {"months": "1-6 → 7",  "win_rate": 0.65, "profit_factor": 1.45, "passed": true},
      {"months": "2-7 → 8",  "win_rate": 0.63, "profit_factor": 1.38, "passed": true},
      {"months": "3-8 → 9",  "win_rate": 0.58, "profit_factor": 1.18, "passed": false},
      {"months": "4-9 → 10", "win_rate": 0.69, "profit_factor": 1.62, "passed": true},
      {"months": "5-10 → 11","win_rate": 0.66, "profit_factor": 1.48, "passed": true},
      {"months": "6-11 → 12","win_rate": 0.64, "profit_factor": 1.41, "passed": true}
    ],
    "splits_passed": 5,
    "splits_required": 4,
    "passed": true
  },
  
  "regime_analysis": {
    "trending_up":    {"take_rate": 0.72, "win_rate": 0.68},
    "trending_down":  {"take_rate": 0.70, "win_rate": 0.65},
    "ranging":        {"take_rate": 0.45, "win_rate": 0.57},
    "high_volatility":{"take_rate": 0.58, "win_rate": 0.62},
    "low_volatility": {"take_rate": 0.35, "win_rate": 0.54}
  },
  
  "vs_baseline": {
    "baseline_win_rate": 0.58,
    "filtered_win_rate": 0.67,
    "baseline_profit_factor": 1.21,
    "filtered_profit_factor": 1.52,
    "baseline_max_drawdown": 0.089,
    "filtered_max_drawdown": 0.054,
    "drawdown_reduction": 0.39,
    "total_pnl_change": "+12%"
  },
  
  "verdict": "PASS — deploy to shadow mode"
}
```

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **Evaluation runner** | `app/rl/evaluate.py` | Expands the basic evaluator from 13.5 with all 4 protocols. |
| 2 | **Walk-forward splitter** | `app/rl/evaluate.py` | `walk_forward_splits(data, train_months=6, test_months=1, step_months=1)` — generates the overlapping train/test splits. |
| 3 | **Walk-forward trainer** | `app/rl/evaluate.py` | For each split, trains a fresh agent and evaluates. Aggregates results. |
| 4 | **Regime tagger** | `app/rl/evaluate.py` | `tag_regime(h1_candles) -> str` — uses ADX and ATR trends to classify periods. |
| 5 | **Baseline comparator** | `app/rl/evaluate.py` | Runs unfiltered strategy on same data, computes delta metrics. |
| 6 | **Report generator** | `app/rl/evaluate.py` | Produces JSON + human-readable summary. |
| 7 | **CLI command** | `app/rl/evaluate.py` | `python -m app.rl.evaluate --model models/forge_agent/best_model.zip --data data/historical/XAU_USD/` |
| 8 | **Tests** | `tests/test_rl_eval.py` | Walk-forward split correctness, regime tagging on synthetic data, report schema validation. |

#### Acceptance Criteria

1. Holdout test runs on 15% of data and produces all 6 metrics.
2. Walk-forward generates exactly 6 splits from 12 months of data.
3. Walk-forward trains and evaluates independently for each split (no data leakage between splits).
4. Regime tagger produces labels for all common Gold market conditions.
5. Baseline comparison uses identical data and SL/TP logic as filtered evaluation.
6. Report JSON is generated and validates against schema.
7. Agent must pass holdout and walk-forward criteria to proceed to Phase 13.7.
8. If agent fails criteria, the report clearly identifies which thresholds were missed and in which regimes/splits.

---

### Phase 13.7 — Live Integration (Shadow Mode → Active)

#### Purpose

Wire the trained ForgeAgent model into the live trading engine as a trade filter. Deployment follows a graduated rollout: first **shadow mode** (logs decisions but doesn't veto), then **active mode** (actually vetoes trades below confidence threshold).

#### Shadow Mode

The agent runs alongside every trade decision but has no power to block trades. It logs what it *would* have done. After 2-4 weeks of shadow data, compare:

```
Shadow mode logging:
  ├── For each signal from TrendScalpStrategy:
  │   ├── Build state vector (same as training)
  │   ├── Agent predicts: action, confidence
  │   ├── Log: {timestamp, signal, state_hash, action, confidence, actual_outcome}
  │   └── Trade executes regardless of agent opinion
  │
  └── After 2+ weeks, analyze:
      ├── If agent vetoed and trade lost → "correct veto" count
      ├── If agent vetoed and trade won → "missed winner" count
      ├── If agent took and trade won → "correct take" count
      ├── If agent took and trade lost → "incorrect take" count
      └── Calculate: theoretical improvement if agent was active
```

**Activation criteria**: Agent's theoretical performance must show:
- Correct veto rate ≥ 60% (of the trades it vetoed, 60%+ were losers)
- Improvement in win rate ≥ +3% vs unfiltered
- Improvement in profit factor ≥ +10% vs unfiltered
- No trade it vetoed was a >2R winner more than 10% of the time (not missing big moves)

#### Active Mode Integration

```python
# In engine.py, within the tick() method:

# After strategy produces a signal:
result = await self._strategy.evaluate(self._broker, eng_config)

if result is not None and self._rl_filter is not None:
    # Build state vector from current market data
    state = self._state_builder.build(
        m5_candles=...,
        m1_candles=...,
        h1_candles=...,
        m15_candles=...,
        account_state=self._get_account_state(),
    )
    
    # Agent decides
    action, confidence = self._rl_filter.assess(state)
    
    if action == 0:  # VETO
        logger.info(
            "ForgeAgent VETOED %s %s signal (confidence=%.2f)",
            result.signal.direction,
            self.instrument,
            confidence,
        )
        # Update dashboard insight
        update_strategy_insight(
            self.stream_name,
            {"rl_filter": "vetoed", "confidence": round(confidence, 3)},
        )
        result = None  # Suppress the trade
    else:
        logger.info(
            "ForgeAgent APPROVED %s %s signal (confidence=%.2f)",
            result.signal.direction,
            self.instrument,
            confidence,
        )
        update_strategy_insight(
            self.stream_name,
            {"rl_filter": "approved", "confidence": round(confidence, 3)},
        )
```

#### RLFilter Class

```python
class RLTradeFilter:
    """Wraps a trained PPO model for live trade filtering.
    
    Loads a saved SB3 model and exposes a simple assess() interface.
    Thread-safe (PyTorch inference is safe for concurrent reads).
    Stateless per-call — no side effects.
    """
    
    def __init__(self, model_path: str, confidence_threshold: float = 0.6):
        self.model = PPO.load(model_path)
        self.threshold = confidence_threshold
    
    def assess(self, state: np.ndarray) -> tuple[int, float]:
        """Assess a trade signal.
        
        Args:
            state: ForgeState as numpy array, shape (27,).
        
        Returns:
            (action, confidence) where:
            - action: 0 (VETO) or 1 (TAKE)
            - confidence: probability assigned to the chosen action [0.5, 1.0]
        """
        action, _states = self.model.predict(state, deterministic=True)
        
        # Extract action probabilities for confidence
        obs_tensor = torch.as_tensor(state).float().unsqueeze(0)
        with torch.no_grad():
            dist = self.model.policy.get_distribution(obs_tensor)
            probs = dist.distribution.probs.numpy()[0]
        
        confidence = float(probs[action])
        return int(action), confidence
```

#### Dashboard Integration

The dashboard shows the RL filter's status in the strategy insight panel:

```
┌─────────────────────────────────────────────────────────┐
│  MICRO-SCALP (XAU_USD)                                  │
│                                                         │
│  Strategy: Momentum Scalp                               │
│  Bias: ● BULLISH (M1)                                  │
│                                                         │
│  ForgeAgent: ● ACTIVE                                   │
│  ├── Last signal: APPROVED (conf: 0.83)                 │
│  ├── Session stats: 8 taken / 3 vetoed (73% take rate)  │
│  ├── Veto accuracy: 2/3 correct (67%)                   │
│  └── Model: best_model.zip (trained 2026-03-15)         │
│                                                         │
│  Checks:                                                │
│  ✓ Bias detected  ✓ Volatility OK  ✓ Pullback to EMA   │
│  ✓ Spread OK      ✓ Confirmation   ✓ SL valid           │
│  ✓ RL filter passed                                     │
└─────────────────────────────────────────────────────────┘
```

When the agent vetoes:

```
│  ForgeAgent: ● ACTIVE                                   │
│  ├── Last signal: VETOED (conf: 0.71)                   │
│  ├── Reason: Low confidence — late session + high spread │
│  ...                                                    │
│  ✓ Bias detected  ✓ Volatility OK  ✓ Pullback to EMA   │
│  ✓ Spread OK      ✓ Confirmation   ✓ SL valid           │
│  ✗ RL filter vetoed                                     │
```

#### Configuration

```json
// In forge.json, micro-scalp stream:
{
  "name": "micro-scalp",
  "instrument": "XAU_USD",
  "strategy": "trend_scalp",
  "rl_filter": {
    "enabled": true,
    "mode": "shadow",           // "shadow" | "active" | "disabled"
    "model_path": "models/forge_agent/best_model.zip",
    "confidence_threshold": 0.6,
    "log_decisions": true
  }
}
```

Mode transitions:
- `"disabled"` → no RL filter, strategy operates as before (default)
- `"shadow"` → RL filter logs but doesn't veto (data collection mode)
- `"active"` → RL filter vetoes trades below confidence threshold

#### Model Retraining Cadence

The model should be retrained periodically as market conditions evolve:

| Cadence | What | Why |
|---------|------|-----|
| **Monthly** | Download last month's new data, append to training set, retrain | Market microstructure drifts. Session patterns shift with DST changes. New psychological levels form. |
| **After regime change** | If Gold moves to a new $500 range (e.g., $5000→$5500), retrain immediately | Round number features shift. ATR scales may change. |
| **After poor performance** | If live win rate drops below 55% for 2+ weeks, retrain with recent data weighted higher | Model may have degraded due to distribution shift. |

Retraining uses the same pipeline from Phase 13.5, just with updated data. The old model is kept as fallback.

#### Implementation Items

| # | Item | File(s) | Description |
|---|------|---------|-------------|
| 1 | **RL filter class** | `app/rl/filter.py` | `RLTradeFilter` — loads model, exposes `assess()`. |
| 2 | **State builder integration** | `app/rl/features.py` | `ForgeStateBuilder.build_live()` — builds state from live broker data (handles async candle fetches). |
| 3 | **Engine integration** | `app/engine.py` | Add `_rl_filter` optional param to `TradingEngine`. Insert filter check after strategy evaluation, before order placement. |
| 4 | **Shadow mode logging** | `app/rl/filter.py` | `ShadowLogger` — records all decisions with timestamps and actual outcomes for later analysis. Writes to `data/rl_shadow_log.jsonl`. |
| 5 | **Dashboard updates** | `app/static/index.html`, `app/api/routers.py` | Add RL filter status to insight panel. New API field in `/status`. |
| 6 | **forge.json config** | `app/config.py`, `app/models/stream_config.py` | Parse `rl_filter` config from stream definition. |
| 7 | **Shadow analysis script** | `app/rl/analyze_shadow.py` | `python -m app.rl.analyze_shadow --log data/rl_shadow_log.jsonl` — analyzes shadow mode performance and outputs activation recommendation. |
| 8 | **Tests** | `tests/test_rl_filter.py` | Filter loads model and produces valid action/confidence. Shadow logger writes correct format. Engine correctly vetoes when filter returns 0. Engine proceeds when filter returns 1. Engine proceeds when no filter is configured (backward compat). |

#### Acceptance Criteria

1. `RLTradeFilter("models/forge_agent/best_model.zip")` loads without errors.
2. `filter.assess(state)` returns `(action, confidence)` where action ∈ {0, 1} and confidence ∈ [0.5, 1.0].
3. Inference latency < 10ms per call (must not slow the trading loop).
4. Shadow mode: all signals are logged to JSONL with correct schema. No trades are vetoed.
5. Active mode: signals with confidence below threshold are vetoed. Vetoed signals logged but not executed.
6. Engine with `rl_filter=None` (disabled) behaves identically to pre-Phase-13 engine (backward compatibility).
7. Dashboard displays ForgeAgent status, confidence, and session statistics.
8. `forge.json` rl_filter config is parsed and respected for each stream independently.
9. Shadow analysis script produces activation recommendation based on configurable thresholds.

---

### Phase 13 — Dependency & Build Summary

#### Full Dependency Graph

```
Phase 13.0 (Data Collection)
     │
     ├──── Phase 13.1 (Feature Engineering)
     │         │
     │         ├──── Phase 13.2 (Gym Environment)
     │         │         │
     │         │         ├──── Phase 13.3 (Reward Shaping)
     │         │         │         │
     │         │         │         └──── Phase 13.4 (Neural Network)
     │         │         │                    │
     │         │         └────────────────────┤
     │         │                              │
     │         └──────────────────────────────┤
     │                                        │
     └────────────────────────────────────────┤
                                              ▼
                                   Phase 13.5 (Training Pipeline)
                                              │
                                              ▼
                                   Phase 13.6 (Evaluation & Validation)
                                              │
                                              ▼
                                   Phase 13.7 (Live Integration)
```

#### New Files Created

| File | Sub-Phase | Purpose |
|------|-----------|---------|
| `app/rl/__init__.py` | 13.0 | Package init |
| `app/rl/data_collector.py` | 13.0 | Historical data download + clean + store |
| `app/rl/features.py` | 13.1 | ForgeState, ForgeStateBuilder, normalization utils |
| `app/rl/environment.py` | 13.2 | ForgeTradeEnv (Gymnasium), trade simulator, noise wrapper |
| `app/rl/rewards.py` | 13.3 | Reward function, RewardConfig, AccountState, counterfactual |
| `app/rl/network.py` | 13.4 | ForgeFeatureExtractor, PPO_CONFIG, build_agent() |
| `app/rl/train.py` | 13.5 | Training script, callbacks, CLI entry |
| `app/rl/evaluate.py` | 13.6 | All 4 evaluation protocols, walk-forward, regime, report |
| `app/rl/filter.py` | 13.7 | RLTradeFilter, ShadowLogger |
| `app/rl/analyze_shadow.py` | 13.7 | Shadow mode performance analysis |
| `tests/test_rl_data.py` | 13.0 | Data collection tests |
| `tests/test_rl_features.py` | 13.1 | Feature engineering tests |
| `tests/test_rl_env.py` | 13.2 | Environment tests |
| `tests/test_rl_rewards.py` | 13.3 | Reward function tests |
| `tests/test_rl_network.py` | 13.4 | Network architecture tests |
| `tests/test_rl_train.py` | 13.5 | Training pipeline tests |
| `tests/test_rl_eval.py` | 13.6 | Evaluation tests |
| `tests/test_rl_filter.py` | 13.7 | Live filter tests |

#### New Dependencies

| Package | Version | Sub-Phase | Purpose |
|---------|---------|-----------|---------|
| `pandas` | >= 2.0 | 13.0 | Data manipulation |
| `pyarrow` | >= 14.0 | 13.0 | Parquet file I/O |
| `gymnasium` | >= 0.29 | 13.2 | RL environment framework |
| `stable-baselines3` | >= 2.0 | 13.4 | PPO implementation |
| `torch` | >= 2.0 | 13.4 | Neural network backend (auto-installed with SB3) |
| `tensorboard` | >= 2.14 | 13.5 | Training metrics visualization |

#### Estimated Effort per Sub-Phase

| Sub-Phase | Effort | Risk | Key Challenge |
|-----------|--------|------|---------------|
| 13.0 Data Collection | 3-4 hours | Low | OANDA pagination edge cases |
| 13.1 Feature Engineering | 4-5 hours | Medium | Getting normalization right for all 27 features |
| 13.2 Gym Environment | 6-8 hours | High | M1-resolution trade simulation correctness |
| 13.3 Reward Shaping | 4-6 hours | **Highest** | Reward design determines training success |
| 13.4 Neural Network | 2-3 hours | Low | Mostly configuration of proven architecture |
| 13.5 Training Pipeline | 4-5 hours | Medium | Parallel envs + TensorBoard + early stopping |
| 13.6 Evaluation | 5-7 hours | Medium | Walk-forward requires multiple full training runs |
| 13.7 Live Integration | 3-4 hours | Low | Engine wiring + dashboard updates |
| **Total** | **31-42 hours** | | |

#### Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Insufficient data** — 12 months may not cover enough regime diversity | Medium | High | Extend to 18-24 months if OANDA allows. Alternatively, augment with synthetic data (time-shifted replays). |
| **Overfitting** — agent memorizes training data | High | Critical | Walk-forward validation (13.6), noise injection (13.5), small network (13.4), regime testing. |
| **Reward hacking** — agent games reward function | Medium | High | Counterfactual veto scoring prevents "always veto" exploit. Take rate bounds ensure agent isn't degenerate. |
| **Distribution shift** — live market differs from training data | High | Medium | Monthly retraining with new data. Shadow mode catches degradation before live impact. Fallback to disabled mode. |
| **Inference latency** — model prediction slows trading loop | Low | Low | 20K param model runs in <1ms. Even with state building overhead, <10ms total is easy. |
| **Dependency bloat** — PyTorch + SB3 are large packages | Certain | Low | Acceptable — these are standard ML libraries. ~2GB disk, ~500MB RAM during training. Inference RAM is minimal. |

---

*Phase 13 was designed to transform ForgeTrade's gold scalping from a rigid rule-based system into an adaptive, learning-augmented trading agent. ForgeAgent sits on top of the proven momentum-bias strategy, adding a quality filter that no amount of hand-coded rules could replicate. The phased rollout (shadow → active) ensures zero risk to live capital during development and validation.*

---

*This plan was generated by the Forge Director. Each phase should be built, tested, and authorized sequentially before proceeding to the next.*
