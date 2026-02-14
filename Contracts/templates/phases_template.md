# {PROJECT_NAME} — Build Phases

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
| 1 | Directory structure | Per `stack.md` — backend dirs, frontend dirs (if enabled), config dirs |
| 2 | `Contracts/` populated | `blueprint.md`, `manifesto.md`, `stack.md`, `schema.md`, `physics.yaml`, `boundaries.json`, `ui.md` — all provided by director, builder copies them into place |
| 3 | `evidence/` directory | With empty `updatedifflog.md` (will be finalized end of phase) |
| 4 | `scripts/run_tests.ps1` | Copied from Forge, functional for declared stack |
| 5 | `scripts/run_audit.ps1` | Copied from Forge, functional with project's `boundaries.json` |
| 6 | `scripts/overwrite_diff_log.ps1` | Copied from Forge (generic, no customization needed) |
| 7 | `forge.json` | Machine-readable project config (schema defined in `stack.md`) |
| 8 | `.env.example` | From `stack.md` environment variables table (values are examples, not secrets) |
| 9 | Dependency file(s) | `requirements.txt` / `package.json` / `go.mod` with initial dependencies |
| 10 | `db/migrations/001_initial_schema.sql` | From `schema.md` — valid SQL, NOT executed (no DB connection yet) |
| 11 | App entry point | Boots and serves `/health` endpoint. Returns `{"status": "ok"}`. No other functionality. |
| 12 | Test configuration | `pytest.ini` / `tsconfig.json` / equivalent + one passing health check test |
| 13 | `.gitignore` | Appropriate for the stack |
| 14 | `git init` + initial commit | Repository initialized with all Phase 0 files |

### forge.json

The builder creates `forge.json` at the project root based on `stack.md`. This file is read by the test runner and audit script for stack-aware behavior.

```json
{
  "project_name": "{PROJECT_NAME}",
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
    "dir": "web",
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
6. `db/migrations/001_initial_schema.sql` contains valid SQL matching `schema.md`.
7. `git log` shows one initial commit.

### Verification Gates

| Gate | Check |
|------|-------|
| **Static** | Lint/type check passes (e.g., `compileall`, `tsc --noEmit`, `go vet`) |
| **Runtime** | App boots, `/health` responds 200 |
| **Behavior** | Health test passes via test runner |
| **Contract** | All Contracts/ files present. Physics declares `/health`. Boundaries.json parseable. |

### Post-Phase 0

After Phase 0 is `AUTHORIZED` and committed:
- **§1 read gate is ACTIVE** for all subsequent phases.
- **Full audit enforcement** (A1–A9) applies.
- The builder MUST read all contract files before beginning Phase 1.

---

## Phase 1 — {FIRST_FEATURE_NAME}

<!-- DIRECTOR: Each subsequent phase follows this structure.
     Copy this template for each phase in the build plan. -->

### A) Purpose and UX Target

<!-- What does this phase deliver from the user's perspective? -->

### B) Current Constraints

<!-- What exists in the codebase at phase start that the builder must understand?
     Reference specific files, functions, schemas. -->

### C) Scope

#### Constraints
- {What this phase does NOT do}
- {What endpoints/files are affected}

#### Implementation Items

| # | Item | Description |
|---|------|-------------|
| 1 | {ITEM_1} | {What to implement} |
| 2 | {ITEM_2} | {What to implement} |

### D) Non-Goals (Explicitly Out of Scope)

- {NON_GOAL_1}
- {NON_GOAL_2}

### E) Acceptance Criteria

#### Functional
1. {CRITERIA_1}
2. {CRITERIA_2}

#### Unit Tests

| Test case | Asserts |
|-----------|---------|
| {test_1} | {assertion} |
| {test_2} | {assertion} |

### F) Verification Gates

| Gate | Check |
|------|-------|
| **Static** | {What static checks must pass} |
| **Runtime** | {What runtime checks must pass} |
| **Behavior** | {What behavioral checks must pass} |
| **Contract** | {What contract alignment to verify} |
| **Regression** | All existing tests pass (`scripts/run_tests.ps1`) |

### G) Implementation Entrypoint Notes

| Component | File | Function / Line |
|-----------|------|-----------------|
| {COMPONENT_1} | `{file_path}` | `{function}` |

---

<!-- DIRECTOR: Repeat the Phase N template for each subsequent phase.
     
     Guidelines for phasing:
     - Each phase should be completable in a single AEM session (ideally 1-3 hours of builder work).
     - Phases should build on each other — Phase N assumes Phase N-1 is complete.
     - Each phase must have testable acceptance criteria.
     - Keep phases focused: one feature area per phase.
     - Include "Current Constraints" (§B) so the builder understands the codebase state.
     
     Typical phase ordering:
     Phase 0: Genesis (always first)
     Phase 1: Auth / user management (if applicable)
     Phase 2: Core data model + CRUD
     Phase 3: Primary feature
     Phase 4: Secondary features
     Phase 5: Frontend (if applicable)
     Phase 6+: Refinements, integrations, polish
-->
