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

*This plan was generated by the Forge Director. Each phase should be built, tested, and authorized sequentially before proceeding to the next.*
