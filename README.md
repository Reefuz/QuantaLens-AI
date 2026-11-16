# QuantaLens AI

*See Beyond the Data.*

QuantaLens AI is an analytics workspace for messy data. Upload a CSV, review and approve fixes for its quality problems, then ask
questions in plain English. An AI analyst writes and runs real SQL and Python against your data, draws charts, re-checks its own
numbers, and shows you everything it ran.

**Live demo: https://quantalens-ai.vercel.app**

> The engine runs on Render's free plan and sleeps when idle, so the first request after a pause can take up to a minute.
> The AI uses Gemini's free tier, so answers can take one to three minutes when the model is busy.

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Tech stack](#tech-stack)
- [Getting started](#getting-started)
- [Testing](#testing)
- [Deployment](#deployment)
- [Security](#security)
- [Limitations](#limitations)
- [Project structure](#project-structure)

## Features

### Data preparation
- **CSV upload** with progress, up to 50 MB, or a built-in synthetic banking sample with deliberate errors.
- **Profiling** of every column: detected type, missing values and placeholders, distinct and common values, ranges.
- **Quality checks** for duplicates, duplicate IDs, mixed types, currency formatting, mixed date formats, inconsistent categories,
  stray whitespace, outliers, and empty or constant columns.
- **Approve-before-apply cleaning.** Each fix is a proposal with a preview. Nothing changes until you approve it.
  The original upload is kept exactly as received, and the cleaned version is a separate table.

### AI analyst
- Ask questions in plain English, with follow-ups in the same conversation.
- The agent decides which tools to use: inspect the dataset, plan, run SQL, run Python (pandas, SciPy, scikit-learn),
  draw a chart, validate results, or ask you for a missing detail.
- **Live timeline.** Each step streams to the browser as it happens. If you close the tab, the analysis keeps running and is saved.
- **Full transparency.** The SQL tab shows the exact statement sent to the database, and the Python tab shows the code and its output.
- **Validation.** Key figures are recalculated independently, and rankings are checked. Any number in the written answer that doesn't
  match a result is flagged. Results are labelled verified, unverified or not validated. Nothing unchecked is marked as verified.
- Eleven chart types, each viewable as a chart, a table or raw data.

### Reports and history
- Export any answer as a **PDF report** (vector charts), an **Excel workbook** (summary, validation, queries, one sheet per result,
  native charts) or a **CSV** of any result. Exports use the stored results, so they match what you saw.
- **Analysis History** with search and filters by dataset and outcome.

### Account
- Email and password sign-up and login. You can change your password, sign out other devices, see your storage use,
  delete all your data, or delete your account.

## How it works

```
Browser ──► Next.js on Vercel ──(/api/* rewrite)──► FastAPI engine on Render ──► Neon PostgreSQL
                                                         │
                                                         ├─► Gemini (OpenAI-compatible API)
                                                         └─► Python sandbox (child process)
```

- The browser talks only to the Vercel site. Vercel forwards `/api/*` to the engine, so session cookies are first-party and the
  browser never needs CORS.
- The engine owns authentication, data storage, profiling, cleaning, the AI agent, and report generation.
- Each dataset lives in its own table in a separate `qdata` schema. Generated SQL runs under a **read-only database role**, after a
  guard that allows only a single `SELECT` on that dataset.
- Generated Python runs in a separate process with no environment variables, restricted imports and built-ins, a file-access audit
  hook, and CPU, memory and time limits.

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16 (App Router), TypeScript, Tailwind CSS v4, shadcn/ui, Recharts, TanStack Table |
| Engine | Python 3.11, FastAPI, SQLAlchemy 2, Alembic, pandas, SciPy, scikit-learn, sqlglot |
| AI | Google Gemini (`gemini-3.5-flash`, falling back to `gemini-3.1-flash-lite`) |
| Database | Neon serverless PostgreSQL |
| Reports | reportlab (PDF), openpyxl (Excel) |
| Auth | Argon2id password hashing, HttpOnly session cookies, CSRF header check |
| Hosting | Vercel (frontend), Render with Docker (engine) |

## Getting started

### Prerequisites
- Node.js 20 or later
- Python 3.11
- A [Neon](https://neon.tech) project (the free plan is enough)
- A [Google AI Studio](https://aistudio.google.com) API key (the free tier is enough)

### 1. Configure the engine

```bash
cp .env.example apps/engine/.env
```

Open `apps/engine/.env` and set at least `DATABASE_URL`, `AUTH_SECRET` and `AI_PROVIDER_API_KEY`.
The comments in the file explain each value. Never commit this file. It is git-ignored.

### 2. Run the engine

```bash
cd apps/engine
python3.11 -m venv .venv            # on Windows: py -3.11 -m venv .venv
source .venv/bin/activate           # on Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt -c constraints.txt
alembic upgrade head
python -m scripts.provision_readonly_role   # creates the read-only SQL role and writes its URL to .env
uvicorn app.main:app --port 8000
```

### 3. Run the frontend

In a second terminal:

```bash
cd apps/web
npm install
echo "PYTHON_ANALYTICS_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Open http://localhost:3000, create an account, and click **Use sample dataset** to try it.

## Testing

Run these from `apps/engine` with the virtual environment active:

| Command | What it checks |
|---|---|
| `python -m pytest` | Unit tests (about 470; SQLite, no network) |
| `RUN_INTEGRATION=1 python -m pytest tests/integration` | Against a real Neon database (about 9 minutes; cleans up after itself) |
| `python -m scripts.check_connections` | That Neon and Gemini are reachable |
| `python -m scripts.verify_readonly_role` | That the SQL role cannot write or read app tables |
| `python -m scripts.e2e_web` | End to end through the frontend (needs both servers running) |
| `python -m scripts.smoke_prod <site-url> --engine <engine-url>` | Production smoke test (creates and deletes a throwaway account) |

Frontend: `cd apps/web && npm run lint && npm run build`.

A GitHub Actions workflow is provided at [`docs/ci.yml.example`](docs/ci.yml.example). To enable it, copy it to `.github/workflows/ci.yml`.

## Deployment

The engine deploys to Render from [`render.yaml`](render.yaml) (Docker, free plan). The frontend deploys to Vercel with `apps/web` as
the root directory. Pushing to `main` redeploys both. Step-by-step instructions, environment variables and the smoke test are in
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).

## Security

- Passwords are hashed with Argon2id. Sessions are opaque random tokens stored as keyed hashes.
- Cookies are HttpOnly, Secure and SameSite. State-changing requests require a CSRF header.
- Login, registration, uploads and analyses are rate-limited.
- Generated SQL runs read-only with a 10-second timeout and a 1,000-row cap.
- Exports defuse spreadsheet formulas.
- Production sets a strict Content Security Policy and HSTS.
- In production the engine refuses to start with missing or weak secrets.

The Python sandbox is defence in depth, not a hardened container. [`SECURITY.md`](SECURITY.md) explains what each control does and
does not protect against.

## Limitations

- **Answer quality depends on the model.** The free tier is often rate-limited, so many answers come from the weaker fallback model.
  The validation checks catch some mistakes but not all. Check the Validation tab.
- Totals computed on the original (uncleaned) text columns cannot be independently verified. Clean the dataset first.
- Only CSV files are supported. Excel uploads and connecting to external databases are not built.
- No email verification, password reset or two-factor authentication.
- Background jobs run inside the engine process. If the engine restarts mid-job, the dataset is marked failed.
- Export tables hold at most 300 rows each. Area charts appear as line charts in PDFs.

Sample data in this product is synthetic. Nothing in the UI is simulated: every result comes from a real query or computation.

## Project structure

```
apps/
  web/                 Next.js frontend
    src/app/           Pages (landing, auth, dashboard, datasets, analyst, history, reports, settings)
    src/components/    UI components
    src/lib/           API client and helpers
  engine/              FastAPI engine
    app/api/           HTTP routes
    app/analysis/      Agent, LLM client, SQL guard, Python sandbox, validation, charts
    app/data/          CSV reading, profiling, cleaning, storage
    app/reports/       PDF, Excel and CSV exports
    app/core/          Security, sessions, rate limiting, middleware
    migrations/        Alembic migrations
    scripts/           Setup, verification and smoke-test scripts
    tests/             Unit and integration tests
docs/                  Architecture, deployment, CI workflow
render.yaml            Render Blueprint for the engine
SECURITY.md            Security model
```

## Licence

No licence has been chosen yet, so all rights are reserved.
