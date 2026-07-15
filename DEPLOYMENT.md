# Deploying SmarterJobHunt on Railway

Four Railway pieces, in this order: **Postgres → backend API → ingestion agent → frontend.**

> **Monorepo note:** if all three services live in one GitHub repo (recommended — `agent/`,
> `backend/`, `frontend/` folders), set each Railway service's **Settings → Source → Root
> Directory** to that folder (`/agent`, `/backend`, `/frontend`) when connecting the repo. Railway
> then only rebuilds a service when files under its own folder change.

## 0. What changed in the code

- `sjh-ingestion-agent.zip` — added `agent/job_sink.py::PostgresJobSink` (upserts jobs/companies
  into Postgres, closes out jobs that vanish from a re-scrape) and
  `agent/company_source.py::PostgresCompanySource` (reads the company list from the DB instead of
  a CSV). New entrypoints: `seed_companies.py` (one-time CSV → DB load) and `run_ingestion_db.py`
  (the DB-to-DB scheduled run).
- `smarterjobhunt-backend.zip` — `db/schema.sql` now has `UNIQUE(companies.name)` and a unique
  index on `jobs(company_id, source_url)` so the agent's upserts work; added a `Procfile` +
  `gunicorn` for Railway.
- `smarterjobhunt-frontend.zip` — `src/lib/api.js` (new) calls the backend and maps its response
  onto the shape `JobCard` already expects; `JobListings.jsx` now fetches real data instead of
  `sampleJobs.js` (that file is now unused — safe to delete later).

## 1. Postgres

In your Railway project: **New → Database → PostgreSQL**. Railway gives it a `DATABASE_URL` —
you'll reference this in the other three services, not retype it.

Load the schema once:
```bash
railway connect postgres   # or use the DATABASE_URL with any psql client
\i db/schema.sql
```
(`db/schema.sql` is in the backend zip.)

## 2. Backend API

New service → deploy from the `smarterjobhunt-backend` repo/zip.

**Env vars:**
- `DATABASE_URL` → reference the Postgres service's `DATABASE_URL` (Railway lets you pick this
  from a dropdown instead of copy-pasting)
- `SECRET_KEY` → any long random string
- `FRONTEND_ORIGIN` → your frontend's Railway URL (fill in after step 4, redeploy to update)
- `BACKEND_ORIGIN` → this backend's own Railway URL (used to build the verification link users click)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `MAIL_FROM` → your email provider's
  SMTP credentials (SendGrid, Mailgun, Postmark, SES SMTP, etc). If `SMTP_HOST` is left unset, the
  backend logs the verification link instead of emailing it — fine for testing, not for production.

Railway will detect the `Procfile` (`web: gunicorn app:app --bind 0.0.0.0:$PORT`) automatically.
Once it's up, hit `https://<backend>.up.railway.app/api/health` — should return `{"status":"ok"}`.

## 3. Ingestion agent

New service → deploy from the `sjh-ingestion-agent` repo/zip (the one that has `Dockerfile`,
`agent/`, `run_ingestion_db.py`).

**Env vars:** `DATABASE_URL` → same Postgres reference as the backend.

**One-time company seed** — run once from your machine (or Railway's shell) pointed at the same
`DATABASE_URL`:
```bash
pip install -r requirements.txt --break-system-packages
python seed_companies.py --input sjh_companies_500.csv
```
This loads your company list into the `companies` table. Add more later by re-running
`seed_companies.py` with a new CSV, or `INSERT`ing directly — it upserts by name.

**Custom Start Command** (Settings → Deploy): override the Dockerfile's default so it runs the
scraper instead of the old Gradio UI:
```
python run_ingestion_db.py
```

**Cron Schedule** (Settings → Deploy → Cron Schedule): e.g. `0 2 * * *` for nightly at 2am. With a
cron schedule set, Railway runs the start command on that schedule and doesn't keep the container
running in between — no need to touch the Dockerfile.

First run, do a smoke test with `python run_ingestion_db.py --limit 10` as the start command to
confirm jobs land in the `jobs` table before pointing it at the full company list.

## 4. Frontend

New service → deploy from the `smarterjobhunt-frontend` repo/zip.

**Env var:** `VITE_API_URL` → the backend's Railway URL from step 2 (e.g.
`https://smarterjobhunt-backend.up.railway.app`).

Railway auto-detects the Vite build (`npm run build`, serves `dist/`). Once deployed, go back to
the backend service and set `FRONTEND_ORIGIN` to this frontend URL, then redeploy the backend so
CORS allows it.

## 5. Verify the full loop

1. Agent run finishes → check `jobs` table has rows (`railway connect postgres` → `select count(*) from jobs;`)
2. Visit the frontend, search a job title that matches something scraped → listings should appear
3. If you get a CORS error in the browser console, double check `FRONTEND_ORIGIN` on the backend
   matches the frontend's exact URL (including `https://`)

## Notes / known gaps

- `job_matches` (the "Match %" ring) stays empty until match scoring is built — search/filtering
  by title works now via `jobs.title ILIKE`, match-scoring is a separate, later piece.
- Registering now requires clicking an emailed verification link before login works. Without a
  real `SMTP_HOST` configured, the link is only logged server-side (check Railway's logs) — set
  real SMTP credentials before sharing the site with anyone but yourself.
- `data/sampleJobs.js` in the frontend is now dead code, safe to delete whenever.
