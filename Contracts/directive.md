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
3. Execute **Phase 0 (Genesis)** per `Contracts/phases.md`.
4. After Phase 0, run the full verification hierarchy (static → runtime → behavior → contract) per §9.
5. Run `scripts/run_audit.ps1` per §10.2. React to the result:
   - **All PASS (exit 0):** Emit a Phase Sign-off per §10.4. Because `Auto-authorize: enabled`, commit and proceed directly to the next phase without halting.
   - **Any FAIL (exit non-zero):** Enter the Loopback Protocol per §10.3. Fix only the FAIL items, re-verify, re-audit. If 3 consecutive loops fail, STOP with `RISK_EXCEEDS_SCOPE`.
6. Repeat steps 3–5 for each subsequent phase in order:
   - Phase 1 — OANDA Broker Client
   - Phase 2 — Strategy Engine
   - Phase 3 — Risk Manager + Order Execution
   - Phase 4 — Trade Logging + CLI Dashboard
   - Phase 5 — Backtest Engine
   - Phase 6 — Paper & Live Integration
7. After the final phase (Phase 6) passes audit and is committed, HALT and report: `"All phases complete."`

## Autonomy Rules

- **Auto-authorize** means: when an audit passes (exit 0), you commit and advance to the next phase without waiting for user input. You do NOT need the `AUTHORIZED` token between phases.
- **You MUST still STOP** if you hit `AMBIGUOUS_INTENT`, `RISK_EXCEEDS_SCOPE`, `CONTRACT_CONFLICT` that cannot be resolved within the loopback protocol, or `ENVIRONMENT_LIMITATION`.
- **You MUST NOT** add features, files, or endpoints beyond what is specified in the contracts. If you believe something is missing from the spec, STOP and ask — do not invent.
- **Diff log discipline** per §11 applies to every phase: read → plan → scaffold → work → finalize. No `TODO:` placeholders at phase end.
- **Re-read contracts** at the start of each new phase (§1 read gate is active from Phase 1 onward).

## Project Summary

ForgeTrade is an automated Forex trading bot that connects to OANDA's v20 REST API and trades EUR/USD using a price action strategy based on support/resistance zones and rejection wicks. It runs locally in a PowerShell terminal as a single-user CLI application with three modes: backtest, paper trading, and live trading. No frontend, no AI — pure deterministic rules with 1% risk per trade and a 10% drawdown circuit breaker.
