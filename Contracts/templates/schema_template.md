# {PROJECT_NAME} — Database Schema

Canonical database schema for this project. The builder contract (§1) requires reading this file before making changes. All migrations must implement this schema. No tables or columns may be added without updating this document first.

---

## Schema Version: 0.1 (initial)

### Conventions

<!-- DIRECTOR: Define the naming and typing conventions for this project's database.
     Adapt to the chosen database engine. -->

- Table names: {CONVENTION} (e.g., snake_case, plural)
- Column names: {CONVENTION} (e.g., snake_case)
- Primary keys: {PK_STRATEGY} (e.g., UUID, auto-increment bigint, ULID)
- Timestamps: {TIMESTAMP_TYPE} (e.g., TIMESTAMPTZ, DATETIME)
- Soft delete: {YES/NO} (if yes, via `deleted_at` column)

---

## Tables

<!-- DIRECTOR: Define each table. Include all columns, types, constraints,
     and relationships. The builder uses this to create migration files in Phase 0.
     
     For each table, include:
     - Table name and purpose (1 sentence)
     - All columns with types, nullability, defaults
     - Primary keys, unique constraints, foreign keys
     - Indexes (if known at design time)
     
     Example below — replace with actual tables. -->

### {table_name_1}

{One-sentence purpose of this table.}

```sql
CREATE TABLE {table_name_1} (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    {column_2}      {TYPE} {NULLABLE} {DEFAULT},
    {column_3}      {TYPE} {NULLABLE} {DEFAULT},
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

<!-- Add indexes if needed -->
```sql
CREATE INDEX idx_{table_name_1}_{column} ON {table_name_1}({column});
```

---

### {table_name_2}

{One-sentence purpose of this table.}

```sql
CREATE TABLE {table_name_2} (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    {fk_column}     UUID NOT NULL REFERENCES {table_name_1}(id),
    {column_2}      {TYPE} {NULLABLE} {DEFAULT},
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

---

<!-- DIRECTOR: Repeat for each table. Keep it minimal — only tables
     needed for MVP features listed in blueprint.md §2. -->

## Migration Files

The builder creates migration files in `db/migrations/` during Phase 0. File naming convention:

```
db/migrations/
  001_initial_schema.sql
  002_{next_migration}.sql
  ...
```

Each migration file contains:
- A `-- Migration: NNN` header comment
- `CREATE TABLE` / `ALTER TABLE` statements
- `CREATE INDEX` statements
- No `DROP` statements in initial migrations

The migration files are created during Phase 0 but NOT executed until a database connection is available. They must be valid SQL that can be run manually or via a migration tool.
