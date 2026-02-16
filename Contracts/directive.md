# Builder Directive — ForgeTrade

You are an autonomous software builder operating under the Forge governance framework.

AEM: enabled.
Auto-authorize: enabled.

## Instructions

1. Read `Contracts/builder_contract.md` — this defines your rules for the entire build.
2. Read **all** contract files listed in §1 of the builder contract:
   - `Contracts/blueprint.md`
   - `Contracts/manifesto.md`
   - `Contracts/stack.md`
   - `Contracts/schema.md`
   - `Contracts/physics.yaml`
   - `Contracts/boundaries.json`
   - `Contracts/ui.md`
   - `evidence/updatedifflog.md` (if it exists)
   - `evidence/audit_ledger.md` (if it exists — summarize last entry or note "No prior audit ledger found")
3. Execute **Phase 7 (Web Dashboard)** per `Contracts/phases.md`.
4. After Phase 7, run the full verification hierarchy (static → runtime → behavior → contract) per §9.
5. Run `scripts/run_audit.ps1` per §10.2. React to the result:
   - **All PASS (exit 0):** Emit a Phase Sign-off per §10.4. Because `Auto-authorize: enabled`, commit and proceed directly to the next phase without halting.
   - **Any FAIL (exit non-zero):** Enter the Loopback Protocol per §10.3. Fix only the FAIL items, re-verify, re-audit. If 3 consecutive loops fail, STOP with `RISK_EXCEEDS_SCOPE`.
6. Repeat steps 3–5 for each subsequent phase in order:
   - Phase 7 — Web Dashboard
   - Phase 8 — Strategy Abstraction + EMA Indicators
   - Phase 9 — Multi-Stream Engine Manager
   - Phase 10 — Trend-Confirmed Micro-Scalp (XAU_USD)
7. After the final phase (Phase 10) passes audit and is committed, HALT and report: `"All phases complete."`

## Autonomy Rules

- **Auto-authorize** means: when an audit passes (exit 0), you commit and advance to the next phase without waiting for user input. You do NOT need the `AUTHORIZED` token between phases.
- **You MUST still STOP** if you hit `AMBIGUOUS_INTENT`, `RISK_EXCEEDS_SCOPE`, `CONTRACT_CONFLICT` that cannot be resolved within the loopback protocol, or `ENVIRONMENT_LIMITATION`.
- **You MUST NOT** add features, files, or endpoints beyond what is specified in the contracts. If you believe something is missing from the spec, STOP and ask — do not invent.
- **Diff log discipline** per §11 applies to every phase: read → plan → scaffold → work → finalize. No `TODO:` placeholders at phase end.
- **Re-read contracts** at the start of each new phase (§1 read gate is active from Phase 1 onward).

## Project Summary

ForgeTrade is an automated trading bot that connects to OANDA's v20 REST API and trades multiple instruments using pluggable strategies. The primary stream trades EUR/USD using S/R rejection wicks on D+H4 timeframes. A secondary stream scalps XAU/USD using trend-confirmed pullbacks on H1/M1/S5 timeframes. A web dashboard provides real-time monitoring. It runs locally in a PowerShell terminal as a single-user application with three modes: backtest, paper trading, and live trading. Pure deterministic rules with configurable risk per trade and a drawdown circuit breaker.
