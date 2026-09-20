# CLAUDE.md — Next.js 15 App Router + SQLite SaaS

## Contract

Build a TypeScript-strict Next.js 15 App Router application on the Node.js runtime with SQLite through `better-sqlite3`. Prefer the smallest server-first change that satisfies the request. Before editing, inspect `package.json`, the nearest route/layout, schema, and latest migration. Never invent tables, environment variables, or commands.

## Stack and versions

- Next.js 15 App Router, React 19, TypeScript 5 in strict mode.
- Node.js 20+ runtime for every database path (`export const runtime = "nodejs"`). SQLite cannot run in Edge middleware or Edge route handlers.
- `better-sqlite3` with one process-local connection; SQL migrations are the schema authority.
- Zod at every untrusted boundary; Vitest for unit/integration tests and Playwright only for critical browser paths.
- Server Components by default. Add `"use client"` only at the smallest interactive leaf, because client boundaries increase shipped JavaScript and cannot import the database.

## Canonical structure

```text
app/
  (marketing)/page.tsx       # public Server Components
  (app)/dashboard/page.tsx   # authenticated Server Components
  api/<resource>/route.ts    # HTTP boundary only; no business logic
  layout.tsx
components/
  ui/                        # reusable presentational components
  <feature>/                 # feature-specific components
lib/
  db/index.ts                # singleton connection + pragmas
  db/queries/<resource>.ts   # typed prepared queries
  validation/<resource>.ts   # Zod input schemas
  services/<resource>.ts     # authorization + business rules
migrations/
  0001_initial.sql           # immutable, ordered, forward-only SQL
scripts/migrate.ts
tests/
  unit/  integration/  e2e/
data/                        # local DB files; gitignored
```

Keep HTTP parsing in routes, authorization/business rules in services, and SQL in `lib/db/queries`. This separation lets tests exercise policy without starting Next.js and prevents database code from leaking into Client Components.

## Naming rules

- Files/folders and route segments: `kebab-case`; React components and exported types: `PascalCase`; functions/variables: `camelCase`.
- SQLite tables/columns/indexes: `snake_case`; tables are plural; foreign keys use `<singular>_id`; timestamps use `<event>_at` as UTC ISO text.
- Name boolean columns with `is_`/`has_`. Name indexes `idx_<table>_<columns>` and unique indexes `uq_<table>_<columns>` so failures are searchable.
- Export verbs that state effects: `getUserById`, `listInvoices`, `createInvoice`; avoid vague `handle`, `process`, or `data`.

## Database connection

```ts
// lib/db/index.ts
import Database from "better-sqlite3";

const globalForDb = globalThis as unknown as { db?: Database.Database };
export const db = globalForDb.db ?? new Database(process.env.DATABASE_PATH ?? "data/app.db");
if (process.env.NODE_ENV !== "production") globalForDb.db = db;
db.pragma("journal_mode = WAL");
db.pragma("foreign_keys = ON");
db.pragma("busy_timeout = 5000");
```

Use prepared statements with bound parameters, explicit selected columns, and transactions for multi-write invariants. The singleton avoids connection churn during development reloads; WAL improves reader/writer coexistence; foreign keys are not reliably enforced unless enabled per connection.

## SQL and migration rules

1. Add one numbered migration for every schema change; never edit a migration already merged, because deployed databases may have applied it.
2. Migrations are forward-only, deterministic, and transaction-safe. Do not read the network, current time, or application state from migration scripts.
3. For destructive changes, use expand/migrate/contract: add nullable structure, backfill in a separately observable step, switch reads/writes, then remove old structure in a later release. SQLite table rebuilds must recreate indexes, constraints, and triggers explicitly.
4. Every foreign key declares intentional `ON DELETE` behavior. Add indexes for foreign keys and measured query predicates; verify non-trivial queries with `EXPLAIN QUERY PLAN`.
5. The migration runner records filename and SHA-256 in `schema_migrations`; abort if an applied checksum changes. Apply pending files in lexical order inside an exclusive transaction.
6. PRs changing SQL must include migration, query/type updates, fresh-database proof, upgrade-from-previous proof, and rollback/restore notes. Never run migrations implicitly during a web request or production build.

Example:

```sql
-- migrations/0002_create_projects.sql
CREATE TABLE projects (
  id INTEGER PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
  created_at TEXT NOT NULL
);
CREATE INDEX idx_projects_owner_id ON projects(owner_id);
```

## Request and component patterns

```ts
// app/api/projects/route.ts
import { NextResponse } from "next/server";
import { createProjectInput } from "@/lib/validation/project";
import { createProject } from "@/lib/services/project";
export const runtime = "nodejs";

export async function POST(request: Request) {
  const parsed = createProjectInput.safeParse(await request.json().catch(() => null));
  if (!parsed.success) return NextResponse.json({ error: "invalid_request", issues: parsed.error.flatten() }, { status: 400 });
  const project = await createProject(parsed.data); // service performs auth/ownership checks
  return NextResponse.json({ project }, { status: 201 });
}
```

- Server Components may call services directly; do not call the app's own API over HTTP from the server.
- Route handlers return stable error codes, not stack traces. Translate known conflicts to 409 and missing records to 404; let unexpected errors reach centralized logging.
- Treat `params`, cookies, headers, forms, JSON, webhooks, and environment variables as untrusted. Validate before authorization and authorize before mutation.
- Use Server Actions only for UI-coupled mutations. Revalidate the narrowest tag/path after success and redirect only after the transaction commits.
- Make retries safe with unique constraints or idempotency keys for billing, webhooks, and job creation.

## Commands

```bash
npm run dev                  # local Next.js server
npm run lint                 # static checks
npm run typecheck            # tsc --noEmit
npm test                     # unit/integration tests
npm run test:e2e             # critical browser paths
npm run db:migrate           # apply reviewed migrations explicitly
npm run db:check             # fresh DB + previous-version upgrade proof
npm run build                # production compilation
```

Use only commands present in `package.json`; add a script and document its dependency before relying on a missing command.

## Patterns to follow

- Return typed domain objects from query modules rather than raw `any` rows, because schema drift should fail during development.
- Wrap related writes in `db.transaction`, assert affected-row counts, and test the failure path, because partial writes corrupt SaaS invariants.
- Pass the database into services in tests, because temporary per-test databases are deterministic and parallel-safe.
- Cache only explicitly public/read-mostly data. User-specific or mutable SQLite reads are uncached by default; invalidate deliberately after writes.
- Keep secrets server-only and fail startup with a clear validation error when required configuration is absent.

## What we do not do (and why)

- **No database import in Client Components or Edge code:** native SQLite requires the Node runtime and server-only filesystem access.
- **No string-built SQL:** parameter binding prevents injection and preserves query-plan reuse.
- **No schema mutation with `db.exec` at startup:** concurrent instances race and unreviewed changes bypass migration evidence.
- **No automatic `SELECT *`:** explicit columns make data exposure and type changes reviewable.
- **No swallowed exceptions or success-shaped fallback data:** false success hides outages and can trigger duplicate writes.
- **No global `force-dynamic` or blanket `no-store`:** choose caching per data boundary instead of disabling platform behavior everywhere.
- **No SQLite file on ephemeral/serverless filesystems:** self-host with a persistent volume, or use Turso/libSQL with the same query/service boundaries.
- **No Prisma/Drizzle alongside direct SQL without an explicit migration-authority decision:** two schema authorities drift.

## Definition of done

A change is done only when lint, typecheck, relevant tests, migration checks (when applicable), and `npm run build` pass; authorization and error paths are covered; README/env examples match reality; and the diff contains no generated DB, credentials, debug logs, or unrelated edits. Report any check that could not run—never replace it with a claim of readiness.
