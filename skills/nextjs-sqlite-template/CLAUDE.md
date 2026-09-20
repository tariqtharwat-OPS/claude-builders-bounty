# CLAUDE.md — Next.js + SQLite Project Guide

This file provides guidance for AI assistants working on this Next.js + SQLite project.

## Project Structure

```
├── app/                    # Next.js App Router
│   ├── api/               # API routes (server actions)
│   ├── layout.tsx         # Root layout
│   └── page.tsx           # Home page
├── lib/
│   ├── db.ts              # Database connection & schema
│   └── utils.ts           # Shared utilities
├── components/            # React components
├── prisma/                # Prisma ORM (if used) or drizzle/
├── public/                # Static assets
├── tests/                 # Test files
├── next.config.js         # Next.js configuration
├── package.json
└── tsconfig.json
```

## Database Schema Conventions

### Using Drizzle ORM (Recommended)

```typescript
// lib/db/schema.ts
import { sqliteTable, text, integer } from 'drizzle-orm/sqlite-core';

export const users = sqliteTable('users', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  email: text('email').notNull().unique(),
  name: text('name'),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull(),
});

export const posts = sqliteTable('posts', {
  id: integer('id').primaryKey({ autoIncrement: true }),
  title: text('title').notNull(),
  content: text('content'),
  authorId: integer('author_id').references(() => users.id),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull(),
});
```

### Using better-sqlite3 Directly

```typescript
// lib/db.ts
import Database from 'better-sqlite3';

const db = new Database('./data/app.db');

// Enable WAL mode for better concurrency
db.pragma('journal_mode = WAL');

export function getUsers() {
  return db.prepare('SELECT * FROM users').all();
}

export function createUser(email: string, name: string) {
  return db.prepare(
    'INSERT INTO users (email, name, created_at) VALUES (?, ?, ?)'
  ).run(email, name, Date.now());
}
```

## API Route Patterns

### GET Endpoint

```typescript
// app/api/users/route.ts
import { NextResponse } from 'next/server';
import { getUsers } from '@/lib/db';

export async function GET() {
  try {
    const users = getUsers();
    return NextResponse.json({ users });
  } catch (error) {
    return NextResponse.json(
      { error: 'Failed to fetch users' },
      { status: 500 }
    );
  }
}
```

### POST Endpoint with Validation

```typescript
// app/api/users/route.ts
import { NextResponse } from 'next/server';
import { z } from 'zod';
import { createUser } from '@/lib/db';

const userSchema = z.object({
  email: z.string().email(),
  name: z.string().min(1).max(100),
});

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const validated = userSchema.parse(body);
    
    createUser(validated.email, validated.name);
    
    return NextResponse.json(
      { message: 'User created' },
      { status: 201 }
    );
  } catch (error) {
    if (error instanceof z.ZodError) {
      return NextResponse.json(
        { error: 'Validation failed', details: error.errors },
        { status: 400 }
      );
    }
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
```

## Testing Conventions

### Unit Tests (Jest/Vitest)

```typescript
// tests/db.test.ts
import { describe, it, expect, beforeEach } from 'vitest';
import { createUser, getUsers } from '../lib/db';

describe('Database operations', () => {
  beforeEach(() => {
    // Reset database before each test
  });

  it('creates a user', () => {
    createUser('test@example.com', 'Test User');
    const users = getUsers();
    expect(users).toHaveLength(1);
    expect(users[0].email).toBe('test@example.com');
  });
});
```

### Integration Tests

```typescript
// tests/api.test.ts
import { describe, it, expect } from 'vitest';
import { GET, POST } from '../app/api/users/route';

describe('Users API', () => {
  it('GET returns users', async () => {
    const response = await GET();
    const data = await response.json();
    expect(response.status).toBe(200);
    expect(data.users).toBeDefined();
  });

  it('POST creates user with valid data', async () => {
    const request = new Request('http://localhost/api/users', {
      method: 'POST',
      body: JSON.stringify({ email: 'test@example.com', name: 'Test' }),
    });
    const response = await POST(request);
    expect(response.status).toBe(201);
  });
});
```

## Common Pitfalls & Gotchas

1. **SQLite File Locking**: Always close connections properly. Use connection pooling or singleton pattern.
2. **Migration Management**: Use Drizzle Kit or manual SQL migrations. Never modify schema without migration script.
3. **Type Safety**: Always validate input with Zod before database operations.
4. **Error Handling**: Wrap all DB calls in try/catch. Return structured error responses.
5. **Performance**: Add indexes on frequently queried columns. Use `EXPLAIN QUERY PLAN` to optimize.
6. **Next.js Caching**: API routes are cached by default. Use `revalidate: 0` or dynamic rendering for real-time data.
7. **Environment Variables**: Store DB path in `.env.local`, never hardcode paths.

## Code Style Preferences

- **TypeScript**: Strict mode enabled. No `any` types.
- **Imports**: Use absolute imports (`@/lib/db`) not relative (`../../lib/db`).
- **Naming**: PascalCase for components/types, camelCase for functions/variables, snake_case for DB columns.
- **Error Handling**: Always return structured JSON errors with appropriate HTTP status codes.
- **Comments**: JSDoc for public functions, inline comments for complex logic only.

## Deployment Notes

1. **Vercel**: SQLite doesn't work on Vercel serverless. Use Turso, PlanetScale, or Supabase instead.
2. **Self-hosted**: Ensure write permissions on SQLite file directory. Set `DB_PATH` environment variable.
3. **Backups**: Implement automated SQLite backups via cron job or Litestream.
4. **Monitoring**: Log slow queries (>100ms). Track connection pool usage.

## Quick Start Commands

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Run tests
npm test

# Build for production
npm run build

# Run migrations (if using Drizzle)
npx drizzle-kit generate
npx drizzle-kit migrate
```
