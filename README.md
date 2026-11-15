# QuantaLens AI

*See Beyond the Data.*

An AI-powered analytical workspace. Upload messy datasets, ask questions in plain English, and inspect the
SQL and Python behind every answer.

> **Status: in development (Phase 1 of 6 complete).** See [Project status](#project-status) for what works today.

## Architecture

```
Browser ─► Next.js (Vercel) ─ rewrite /api/* ─► FastAPI engine (Render) ─► Neon PostgreSQL
```

| Path | Purpose |
|---|---|
| `apps/web` | Next.js 16 (App Router), TypeScript, Tailwind v4, shadcn/ui |
| `apps/engine` | FastAPI, SQLAlchemy, Alembic, pandas/SciPy/scikit-learn |
| `docs/ARCHITECTURE.md` | Design decisions and trade-offs |
| `SECURITY.md` | Security model and its limits |

## Local development

Prerequisites: Node 20+, Python 3.11, a Neon project, and a Google AI Studio API key.

```bash
cp .env.example apps/engine/.env       # fill in values; see comments in the file
cd apps/engine
py -3.11 -m venv .venv && .venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m scripts.provision_readonly_role   # creates the read-only SQL role, writes its URL to .env
.venv/Scripts/python -m uvicorn app.main:app --port 8000

cd ../web
npm install
printf "PYTHON_ANALYTICS_API_URL=http://localhost:8000\n" > .env.local
npm run dev
```

### Tests and checks

```bash
cd apps/engine
.venv/Scripts/python -m pytest                                   # unit tests (SQLite, no network)
.venv/Scripts/python -m scripts.check_connections                # Neon + Gemini reachability
.venv/Scripts/python -m scripts.verify_readonly_role             # proves the SQL role is least-privilege
.venv/Scripts/python -m scripts.e2e_web                          # needs web (3000) and engine (8000) running
cd ../web && npm run lint && npm run build
```

## Project status

| Phase | Scope | State |
|---|---|---|
| 1 Foundation | Repo, design system, landing page, auth, database, migrations | **Done** except Vercel/Render deployment config |
| 2 Data management | CSV ingestion, preview, profiling, cleaning | Not started |
| 3 AI analytics | Agent, SQL and Python execution | Not started |
| 4 Intelligence | Charts, validation, interpretation, follow-ups | Not started |
| 5 Completion | Reports, history, settings, hardening | Not started |
| 6 Deployment | GitHub, Neon production, Vercel, engine hosting | Repo pushed; deployment not started |

Dashboard sections for features that are not built yet say so on the page. Nothing in the UI is simulated.

## Licence

No licence has been selected yet. All rights reserved until one is added.
