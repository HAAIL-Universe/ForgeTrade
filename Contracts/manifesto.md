# ForgeTrade — Manifesto (v0.1)

This document defines the non-negotiable principles for building ForgeTrade.
If implementation conflicts with this manifesto, implementation is wrong.

---

## 1) Product principle: CLI-first, data-backed

ForgeTrade is a CLI-first application that autonomously trades EUR/USD on the Forex market.

- The PowerShell terminal is the primary control and monitoring surface.
- SQLite is the source of truth for trade history and equity records.
- Console output is a real-time display of the bot's current state — it does not control the bot's decisions.

---

## 2) Contract-first, schema-first

ForgeTrade is built from contracts, not vibes.

- `physics.yaml` is the API specification and is canonical.
- SQLite schemas mirror the physics spec.
- If it's not in `physics.yaml`, it isn't real.

---

## 3) No godfiles, no blurred boundaries

Everything has a lane.

- **Entry/CLI** — boot, config, console output, event loop orchestration
- **Strategy** — S/R detection, signal evaluation, session filter (pure functions, no I/O)
- **Broker client** — all OANDA API communication (no logic)
- **Risk manager** — position sizing, SL/TP math, drawdown tracking (no I/O)
- **Repository** — SQLite reads/writes (no logic, no external calls)

No layer is allowed to do another layer's job.
Violations are bugs, even if the feature works.

---

## 4) Auditability over cleverness

We value "debuggable and correct" over "magic and fast."

- Every trade action (entry, exit, modification) is logged to SQLite with timestamps, prices, and reasoning (which S/R zone, which signal).
- Every signal evaluation (hit zone, rejection wick check, session filter pass/fail) is logged at DEBUG level.
- A developer should be able to answer: "Why did the bot take this trade?" by querying the trade log.

---

## 5) Reliability over false signals

The system must be honest about what it sees in the market.

- If candle data is incomplete or stale, the bot must skip the evaluation cycle and log why.
- If the OANDA API returns an error or times out, the bot must NOT place a trade — it retries the data fetch on the next cycle.
- If position sizing results in a trade below OANDA's minimum lot size, the bot must skip and log rather than round up.
- The bot must never fabricate or interpolate candle data.

---

## 6) Confirm-before-write (mode switching)

ForgeTrade must not switch from paper to live mode without explicit user action.

Default flow for mode changes:
1. Mode is set in `.env` or CLI argument at startup
2. On boot, if mode is `live`, the bot logs a prominent warning: "LIVE TRADING ACTIVE — real money at risk"
3. The bot pauses for 5 seconds before entering the trading loop in live mode
4. Mode cannot be changed at runtime — requires restart

### Exempt from confirmation
- Individual trade placement within the configured mode (the bot is autonomous by design)
- Logging and equity snapshots (read-only or append-only operations)
- Drawdown circuit breaker activation (safety mechanism, must fire immediately)

---

## 7) Determinism is sacred

The strategy module must be perfectly deterministic.

- Given the same set of candles, the strategy must produce the same S/R zones, the same signals, every time.
- No randomness, no timestamp-dependent logic in signal evaluation.
- The backtest engine and live engine use the exact same strategy functions — no separate implementations.
- This property must be verified by unit tests: feed known candle data, assert exact signal output.
