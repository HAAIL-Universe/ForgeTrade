# Forge — Autonomous Builder Toolkit

Forge is a contract-driven framework for bootstrapping software projects autonomously using AI builders (Claude, Copilot, Codex, GPT, etc.).

It provides the governance layer — contracts, scripts, and templates — that turns an AI coding agent into a disciplined, auditable builder that can construct a project from an empty folder without human hand-holding.

---

## How It Works

```
┌─────────────────────────────────────────────────────┐
│  1. DIRECTOR SESSION                                │
│     User answers plain-English questions.           │
│     Director produces contract files:               │
│       blueprint.md, manifesto.md, stack.md,         │
│       schema.md, physics.yaml, boundaries.json,     │
│       ui.md, phases.md, directive.md                 │
└────────────────────┬────────────────────────────────┘
                     │  User drops contract files into
                     │  project folder, pastes directive.md
                     │  into builder AI session
                     ▼
┌─────────────────────────────────────────────────────┐
│  2. BUILDER SESSION (autonomous)                    │
│     directive.md primes the builder automatically.  │
│     Phase 0: Genesis — scaffold dirs, scripts,      │
│       configs, forge.json, .env.example,            │
│       initial migration, health endpoint.           │
│     Phase 1+: AEM — full contract enforcement,      │
│       audit gates, loopback protocol,               │
│       phase-by-phase per phases.md.                 │
└─────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
Forge/
├── README.md                          # This file
├── .gitignore
│
├── Contracts/
│   ├── builder_contract.md            # Governs all builder behavior
│   ├── system_prompt.md               # Paste into any chatbot to run a director session
│   └── templates/                     # Skeleton files the director fills out
│       ├── blueprint_template.md
│       ├── manifesto_template.md
│       ├── stack_template.md
│       ├── schema_template.md
│       ├── ui_template.md
│       ├── boundaries_template.json
│       ├── physics_template.yaml
│       └── phases_template.md         # Includes Phase 0: Genesis
│
├── scripts/
│   ├── run_tests.ps1                  # Parameterized test runner
│   ├── run_audit.ps1                  # Deterministic audit (A1–A9)
│   ├── overwrite_diff_log.ps1         # Diff log management
│   └── setup_checklist.ps1            # Post-build setup guide
│
└── evidence/
    └── .gitkeep                       # Placeholder for evidence directory
```

---

## Quick Start

### 1. Run the Director

Open a fresh AI conversation (ChatGPT, Claude, Gemini — anything). Paste the contents of `Contracts/system_prompt.md` into the chat. Answer the questions. The AI will guide you through designing your project and produce all the contract files plus a `directive.md`.

### 2. Set Up the Project Folder

Create an empty folder for your project. Copy the Forge toolkit into it, then place the director's output files into `Contracts/`:
- `Contracts/builder_contract.md` (already in Forge — project-agnostic, don't modify)
- Director's output: `blueprint.md`, `manifesto.md`, `stack.md`, `schema.md`, `physics.yaml`, `boundaries.json`, `ui.md`, `phases.md`, `directive.md` — all go into `Contracts/`
- `scripts/` folder (already in Forge)
- `evidence/` folder (already in Forge)

### 3. Start the Builder

Open an AI coding session (Claude in VS Code, Copilot, Cursor, etc.) pointed at the project folder. Paste or attach `Contracts/directive.md` — that's it. The directive tells the builder who it is, what to read, and what to do. No additional priming needed.

The builder will scaffold the project, run verification, and halt for your `AUTHORIZED` token.

### 4. Continue Phase by Phase

After authorizing Phase 0, tell the builder to continue:

```
Execute Phase 1 per Contracts/phases.md.
```

The builder operates autonomously within each phase, running audit gates and halting for authorization between phases.

### 5. Post-Build Setup

When the build is complete, run the setup checklist to find out what you need to go live:

```
pwsh -File scripts/setup_checklist.ps1
```

It scans your project and tells you exactly what credentials, services, and config values you need — and where to put them.

---

## Key Concepts

| Concept | Description |
|---------|-------------|
| **Builder Contract** | Non-negotiable rules governing the AI builder's behavior: read gates, minimal diffs, file boundaries, verification hierarchy, AEM protocol |
| **System Prompt** | The file you paste into any chatbot to run a director session — plain-English Q&A that produces project contracts |
| **Physics** | The API specification (OpenAPI-style). If it's not in physics, it doesn't exist |
| **Boundaries** | Machine-readable layer rules (which code lives where, what patterns are forbidden) |
| **AEM** | Autonomous Execution Mode — the builder works without step-by-step confirmation, but is audited by deterministic scripts |
| **Phase 0: Genesis** | The bootstrap phase that creates the project structure before normal contract enforcement begins |
| **forge.json** | Machine-readable project config created in Phase 0, read by scripts for stack-aware testing/auditing |
| **Audit Ledger** | Append-only evidence trail of every audit pass/fail, providing cross-session continuity |

---

## Design Principles

1. **Mechanical enforcement, not guidelines.** Rules are checked by scripts, not by asking the AI to be careful.
2. **Contract-first.** If a feature isn't in the contracts, it can't be built. If code diverges from contracts, the build stops.
3. **Auditable.** Every change produces evidence: diff logs, test run logs, audit ledger entries.
4. **Stack-agnostic.** The governance layer works regardless of language, framework, or deployment target. Stack-specific behavior is configured, not hardcoded.
5. **Genesis-aware.** The system knows how to bootstrap itself from nothing, with explicit exemptions for the chicken-and-egg problem.

---

## License

MIT
