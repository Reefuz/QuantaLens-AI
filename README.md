# QuantaLens AI

*See Beyond the Data.*

An AI-powered analytical workspace. Upload messy datasets, ask questions in plain English, and inspect the
SQL and Python behind every answer.

> **Status: in development (Phase 3 of 6 complete).** See [Project status](#project-status) for what works today.

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
RUN_INTEGRATION=1 .venv/Scripts/python -m pytest tests/integration   # real Neon database, about 9 minutes; cleans up after itself
cd ../web && npm run lint && npm run build
```

## Project status

| Phase | Scope | State |
|---|---|---|
| 1 Foundation | Repo, design system, landing page, auth, database, migrations | **Done** except Vercel/Render deployment config |
| 2 Data management | CSV ingestion, preview, profiling, cleaning | **Done** (see notes below) |
| 3 AI analytics | Agent, SQL and Python execution, analyst workspace | **Done** (see notes below) |
| 4 Intelligence | Charts, validation, interpretation, follow-ups | **Mostly built in Phase 3** (charts, validation, follow-ups). Remaining: broader validation coverage, tuning |
| 5 Completion | Reports, history, settings, hardening | Not started |
| 6 Deployment | GitHub, Neon production, Vercel, engine hosting | Repo pushed; deployment not started |

### Phase 2 notes
- The original upload is stored as text, exactly as received, and is never modified. Cleaning builds a separate typed table from approved operations only.
- Profiling covers missing values and placeholders, exact duplicates, duplicate identifiers, mixed types, currency formatting, mixed date formats, inconsistent categories, whitespace, outliers, empty and constant columns.
- Outliers use Tukey fences (1.5 x IQR), on the log scale for positive skewed data. They are flagged, never deleted.
- Ambiguous dates such as 03/04/2024 are resolved from the data where possible; otherwise day-first is assumed and the UI says so.
- Not covered yet: Excel files, non-CSV sources, connecting external PostgreSQL databases, and a worker queue. Background jobs run in the API process, so a restart mid-job leaves the dataset marked failed after 20 minutes.
- Deployment caveat to verify in Phase 6: Vercel may cap request bodies for rewritten routes, which would limit large uploads through the proxy.

### Phase 3 notes
- The agent (Gemini through an OpenAI-compatible endpoint) calls eight tools: `inspect_dataset`, `plan_analysis`, `execute_sql`, `execute_python`, `generate_chart`, `validate_results`, `request_clarification`, `explain_results`. It chooses which to call, and can re-run an analysis when a result is not enough.
- Analyses stream to the browser as they happen. Each timeline step is an event the server actually emitted. The analysis keeps running and is saved if the browser is closed.
- SQL runs through a guard and a read-only database role. Python runs in a restricted child process. **Read `SECURITY.md` for exactly what that does and does not protect against.**
- Eleven chart types, each built server-side from a stored result. Export to CSV and PNG.
- **Free-tier AI limits:** the primary model (`gemini-3.5-flash`) was rate limited during testing, so most answers came from the fallback `gemini-3.1-flash-lite`, which is weaker. Expect slower answers and occasionally clumsier analysis. The UI says when a fallback is used.
- **Answer quality depends on the model.** In testing, the model sometimes misread its own results (for example, claiming the wrong segment had the lowest average) and misused the validation tool. The ranking check, the number scan and the retry rules exist because of those real failures, but they reduce the risk and do not remove it. Read the Validation tab.
- Totals on the original text columns cannot be independently verified. Clean the dataset first for verifiable results.
- Analysis History, Reports and export are Phase 5.

Dashboard sections for features that are not built yet say so on the page. Nothing in the UI is simulated.

## Licence

No licence has been selected yet. All rights reserved until one is added.
