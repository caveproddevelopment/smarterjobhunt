# SJH.com Ingestion Agent — Proof of Concept

This is a **standalone** agent, separate from the MyJobHunt repo. It does
exactly one job: given a list of companies, find every job currently
posted at each one and write it out. No title input, no keyword
matching, no contacts. Those are separate, later steps in SJH.com's
architecture — this agent is purely the nightly batch scrape.

## Why no title/keyword matching here

Matching against a searched job title happens later, at **user search
time**, against whatever's already sitting in the job DB. If this agent
took a title and filtered while scraping, you'd have to re-scrape all
1000+ companies once per unique title searched — instead of once per
company, ever (well, once per scrape cycle).

## Why no contacts here

Contacts (V2) are a separate, on-demand, credit-consuming step — same
principle as MyJobHunt's Tool A / Tool B split. Bundling contact lookups
into an unconditional nightly batch across 1000+ companies would burn
Apollo credits on companies nobody may ever search for.

## Structure

```
agent/
  ats_detector.py            <- unchanged from MyJobHunt, reused as-is
  ats_api.py                 <- unchanged from MyJobHunt, reused as-is
  career_scraper.py          <- unchanged from MyJobHunt, reused as-is
  browser_pool.py            <- unchanged from MyJobHunt, reused as-is
  company_source.py          <- NEW: swappable input (CSV now, MySQL later)
  job_sink.py                 <- NEW: swappable output (CSV now, dataset/DB later)
  ingestion_orchestrator.py  <- NEW: the no-matching, no-contacts batch runner
run_ingestion.py             <- CLI entrypoint (local use)
app.py                       <- Gradio wrapper (Hugging Face Space use)
Dockerfile                   <- Space build config (Playwright/Chromium deps)
requirements.txt
```

## The two swap points

**`company_source.py`** — `CSVCompanySource` reads the same company CSV
format used for the MyJobHunt batch-size tests (Organization Name,
Homepage URL, Last Funding Type, Last Funding Amount, Last Funding
Date). `MySQLCompanySource` is a stub for later — once the company
table schema is settled, that's a one-file swap, not a redesign.

**`job_sink.py`** — `CSVJobSink` writes the job-listing display fields
(minus Match % and contacts) to CSV. `DatasetJobSink` is a stub for the
eventual MySQL `jobs` table — including where upsert-by-`(company,
apply_url)` and "mark closed rather than delete" logic will live.

Nothing in `ingestion_orchestrator.py` needs to change when either swap
happens — it only calls `company_source.load()` and `job_sink.write()`.

## Usage — local CLI

```bash
pip install -r requirements.txt --break-system-packages
playwright install chromium

python run_ingestion.py --input sjh_companies_100.csv --output jobs_100.csv
python run_ingestion.py --input sjh_companies_500.csv --output jobs_500.csv --max-workers 15
```

## Usage — Hugging Face Space

This repo also includes `app.py` (a minimal Gradio wrapper) and a
`Dockerfile`, so the whole folder can be uploaded as-is to a new Space.

**No API keys needed.** This agent never calls Anthropic (no title
input, no keyword expansion) or Apollo (no contacts) — it's pure
HTTP + Playwright, so there's nothing to add under the Space's Secrets.

**Space settings:**
- **SDK:** Docker (not Gradio SDK) — Playwright's Chromium needs the
  system libraries installed in the Dockerfile, which the default
  Space images don't include.
- **Hardware:** CPU Basic (free tier: 2 vCPU, 16GB RAM, 50GB ephemeral
  disk) is enough for a 50–100 company proof-of-concept run.
- **Secrets:** none required.
- **Visibility:** your call — private is fine for a POC.

**To deploy:** create a new Space, choose Docker as the SDK, and
upload every file in this folder (including `Dockerfile` and
`requirements.txt`) to its repo. The Space will build the Docker image
(installs Playwright + Chromium as part of the build) and launch
`app.py`, which serves a simple UI: upload a company CSV, set
concurrency, optionally cap the run to the first N companies for a
smoke test, click Run, download the resulting jobs CSV and timing CSV.

Each run also writes `<output>.timing.csv` — per-company path (`ats_api`
/ `career_scrape` / `error`) and elapsed seconds. That's the data the
batch-size speed test needs: not just total wall-clock time, but the
ATS-hit-rate ratio, which is what actually determines how time scales
past 500 companies toward 1000+.

## Output CSV fields

`company_name, job_title, department, location, apply_url, posted_at,
funding_round, funding_amount, funding_date, ats, careers_url, source,
scraped_at`

## Not yet done (by design — proof of concept first)

- MySQL company source / job sink (stubbed, not implemented)
- Scrape cadence logic (which companies get re-scraped how often)
- Dedup/upsert on re-run (current CSV sink just overwrites)
- Closed-job detection (jobs that disappear from a re-scrape)
