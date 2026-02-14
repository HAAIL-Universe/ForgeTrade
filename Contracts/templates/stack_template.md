# {PROJECT_NAME} — Technology Stack

Canonical technology decisions for this project. The builder contract (§1) requires reading this file before making changes. All implementation must use the technologies declared here unless a directive explicitly approves a change.

---

## Backend

- **Language:** {LANGUAGE} {VERSION}
- **Framework:** {FRAMEWORK}
- **Package manager:** {PACKAGE_MANAGER}
- **Dependency file:** {DEPENDENCY_FILE} (e.g., requirements.txt, package.json, go.mod)

## Database

- **Engine:** {DATABASE_ENGINE} {VERSION}
- **Driver/client:** {DB_DRIVER} (e.g., asyncpg, pg, database/sql)
- **ORM strategy:** {ORM_STRATEGY} (e.g., "raw SQL via repos", "SQLAlchemy", "Prisma", "none")
- **Schema management:** {SCHEMA_MANAGEMENT} (e.g., "manual SQL migrations in db/migrations/", "Alembic", "Prisma migrate")

## Auth

- **Strategy:** {AUTH_STRATEGY} (e.g., "JWT verification via JWKS", "API key", "session-based", "none")
- **Provider:** {AUTH_PROVIDER} (e.g., "Auth0", "Supabase Auth", "self-hosted", "N/A")

## Frontend

- **Enabled:** {YES/NO}
- **Language:** {FRONTEND_LANGUAGE} (e.g., TypeScript, JavaScript)
- **Framework:** {FRONTEND_FRAMEWORK} (e.g., "Vanilla TS + Vite", "React + Vite", "Next.js", "N/A")
- **Directory:** {FRONTEND_DIR} (e.g., "web/", "client/", "frontend/")
- **Build tool:** {BUILD_TOOL} (e.g., Vite, Webpack, Next.js, N/A)

## LLM / AI Integration

- **Enabled:** {YES/NO}
- **Provider:** {LLM_PROVIDER} (e.g., "OpenAI", "Anthropic", "local model", "N/A")
- **Integration point:** {LLM_INTEGRATION} (e.g., "server-side only, dedicated wrapper module", "N/A")
- **Embedding / vector search:** {VECTOR_SEARCH} (e.g., "pgvector", "Pinecone", "N/A")

## Testing

- **Backend tests:** {BACKEND_TEST_FRAMEWORK} (e.g., pytest, vitest, go test)
- **Frontend e2e:** {E2E_FRAMEWORK} (e.g., Playwright, Cypress, N/A)
- **Test directory:** {TEST_DIR} (e.g., "tests/", "__tests__/", "test/")

## Deployment

- **Target:** {DEPLOYMENT_TARGET} (e.g., "single VPS with nginx", "Vercel", "AWS Lambda", "Docker Compose", "local only")
- **Server:** {APP_SERVER} (e.g., "uvicorn", "node", "N/A")
- **Containerized:** {YES/NO}

---

## Environment Variables (required)

<!-- DIRECTOR: List every environment variable the app needs.
     These become the .env.example file in Phase 0. -->

| Variable | Purpose | Example |
|----------|---------|---------|
| `DATABASE_URL` | Database connection string | `postgresql://user:pass@localhost:5432/dbname` |
<!-- Add rows as needed -->

---

## forge.json Schema

The builder must create `forge.json` at the project root during Phase 0. This file is read by `scripts/run_tests.ps1` and `scripts/run_audit.ps1` for stack-aware behavior.

```json
{
  "project_name": "{PROJECT_NAME}",
  "backend": {
    "language": "{LANGUAGE}",
    "entry_module": "{ENTRY_MODULE}",
    "test_framework": "{BACKEND_TEST_FRAMEWORK}",
    "test_dir": "{TEST_DIR}",
    "dependency_file": "{DEPENDENCY_FILE}",
    "venv_path": "{VENV_PATH_OR_NULL}"
  },
  "frontend": {
    "enabled": {TRUE_OR_FALSE},
    "dir": "{FRONTEND_DIR}",
    "build_cmd": "{BUILD_CMD_OR_NULL}",
    "test_cmd": "{TEST_CMD_OR_NULL}"
  }
}
```
