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

*This plan was generated by the Forge Director. Each phase should be built, tested, and authorized sequentially before proceeding to the next.*
