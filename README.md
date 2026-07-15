# SmarterJobHunt

Three services, one repo:

```
agent/      Scraping agent — pulls jobs from company career pages, writes to Postgres.
            Deployed on Railway as a scheduled (cron) job. See agent/README.md.
backend/    Flask API — serves jobs/search/auth/saved-searches to the frontend.
            Deployed on Railway as a web service. See backend/README.md.
frontend/   React/Vite app — the job-search UI.
            Deployed on Railway (or Vercel/Netlify) as a static site.
```

See [`DEPLOYMENT.md`](./DEPLOYMENT.md) for the full Railway setup, in order:
Postgres → backend → agent → frontend.

## Local development

Each service has its own dependencies and `.env.example` — copy to `.env` inside that folder and
fill in real values (all three read `DATABASE_URL` for the same Postgres instance).

```bash
# backend
cd backend && pip install -r requirements.txt --break-system-packages
python app.py                              # http://localhost:5000

# frontend
cd frontend && npm install
npm run dev                                 # http://localhost:5173

# agent (one-time company seed, then a scrape run)
cd agent && pip install -r requirements.txt --break-system-packages
playwright install chromium
python seed_companies.py --input sjh_companies_100.csv
python run_ingestion_db.py --limit 10       # smoke test
```

## Secrets

Nothing in this repo should contain real credentials — `SECRET_KEY`, `DATABASE_URL`, and the SMTP
credentials all come from environment variables (`.env` locally, Railway service variables in
production). Each service's `.gitignore` already excludes `.env`.
