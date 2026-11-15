# Architecture

## Overview

```
Browser ─► Next.js (Vercel) ─ rewrite /api/* ─► FastAPI engine (Render) ─► Neon PostgreSQL
                                                   │
                                                   ├─ LLM provider (OpenAI-compatible, tool calling)
                                                   └─ Restricted Python runner (subprocess)
```

| Layer | Location | Responsibility |
|---|---|---|
| Web | `apps/web` | UI, routing, charts, tables. No business logic, no secrets. |
| Engine | `apps/engine` | Auth, ingestion, profiling, agent, SQL and Python execution, validation, reports. |
| Database | Neon | Application tables, per-dataset tables in schema `qdata`. |

## Decisions

### 1. Separate Python engine
Vercel functions have short execution limits and a read-only filesystem. pandas, SciPy and scikit-learn
workloads and file ingestion do not fit. The engine is a standalone Docker service. Render's free tier is the
default target (free, Docker, Linux). It sleeps when idle, so the first request after inactivity is slow.

### 2. Auth lives in the engine
One component owns users, sessions and authorisation. Passwords use Argon2id. Sessions are random opaque tokens;
only a SHA-256 hash is stored, so a database leak does not yield usable sessions and sessions can be revoked.
The token travels in an `HttpOnly; Secure; SameSite=Lax` cookie.

### 3. Same-origin API via rewrite
`next.config.ts` rewrites `/api/*` to `PYTHON_ANALYTICS_API_URL`. The browser only talks to the web origin, so the
cookie is first-party and CORS is not needed for normal use. State-changing requests also require a custom header
(`X-Requested-With`) as CSRF defence in depth.

### 4. Dataset storage and SQL execution
Each upload becomes a table `qdata.ds_<uuid>` in Neon. Generated SQL is parsed with `sqlglot`, must be a single
`SELECT`, may reference only the current user's dataset tables, and runs under a read-only role with
`statement_timeout` and a forced `LIMIT`. The SQL shown in the UI is the exact string executed.
Constraint: Neon's free tier has 0.5 GB of storage, so uploads are capped (default 50 MB).

### 5. Python execution
Docker is not available on free hosts, and a subprocess is not a security boundary. The runner is
defence in depth: AST allowlist (imports and calls), no `open`/`eval`/`exec`/dunder access, stripped environment,
no database credentials, CPU/memory/wall-clock limits, data passed in as a DataFrame. See `SECURITY.md` for what
this does and does not protect against.

### 6. LLM provider
An OpenAI-compatible client with tool calling. Provider, base URL and model are configuration. When no key is
configured the agent endpoints return a clear "AI not configured" error. There are no canned responses.

### 7. Original and cleaned data
Uploaded data is immutable. Cleaning produces a second table plus an ordered transformation log. Users approve each
operation after seeing a preview.

## Phases
See the project brief. Status is tracked in the README.
