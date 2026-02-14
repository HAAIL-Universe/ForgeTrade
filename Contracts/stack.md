# ForgeTrade — Technology Stack

Canonical technology decisions for this project. The builder contract (§1) requires reading this file before making changes. All implementation must use the technologies declared here unless a directive explicitly approves a change.

---

## Backend

- **Language:** Python 3.11+
- **Framework:** FastAPI (minimal — internal health/status endpoints only)
- **Package manager:** pip
- **Dependency file:** requirements.txt

## Database

- **Engine:** SQLite 3
- **Driver/client:** sqlite3 (Python standard library) or aiosqlite for async
- **ORM strategy:** Raw SQL via repository layer
- **Schema management:** Manual SQL migrations in `db/migrations/`

## Auth

- **Strategy:** None (single user, local only)
- **Provider:** N/A

## Frontend

- **Enabled:** No
- **Language:** N/A
- **Framework:** N/A
- **Directory:** N/A
- **Build tool:** N/A

## LLM / AI Integration

- **Enabled:** No
- **Provider:** N/A
- **Integration point:** N/A
- **Embedding / vector search:** N/A

## Testing

- **Backend tests:** pytest
- **Frontend e2e:** N/A
- **Test directory:** tests/

## Deployment

- **Target:** Local machine (Windows, PowerShell)
- **Server:** uvicorn (for internal FastAPI health endpoint)
- **Containerized:** No

---

## Environment Variables (required)

| Variable | Purpose | Example |
|----------|---------|---------|
| `OANDA_ACCOUNT_ID` | OANDA account ID | `101-001-12345678-001` |
| `OANDA_API_TOKEN` | OANDA v20 API bearer token | `abc123def456...` |
| `OANDA_ENVIRONMENT` | `practice` or `live` | `practice` |
| `TRADE_PAIR` | Instrument to trade | `EUR_USD` |
| `RISK_PER_TRADE_PCT` | Percent of equity risked per trade | `1.0` |
| `MAX_DRAWDOWN_PCT` | Max drawdown from peak before circuit breaker | `10.0` |
| `SESSION_START_UTC` | Trading session start hour (UTC) | `7` |
| `SESSION_END_UTC` | Trading session end hour (UTC) | `21` |
| `DB_PATH` | Path to SQLite database file | `data/forgetrade.db` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `HEALTH_PORT` | Port for internal FastAPI server | `8080` |

---

## forge.json Schema

The builder must create `forge.json` at the project root during Phase 0. This file is read by `scripts/run_tests.ps1` and `scripts/run_audit.ps1` for stack-aware behavior.

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
