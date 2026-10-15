# Reactivate returning jobs: instructions for Claude in Chrome

A new nightly step. When a job that was set to inactive shows up again in the latest scrape, set it
back to active. Change only `is_active` and `scraped_at`. Title, description, date posted and every
other column stay as they are.

## Where it goes in the nightly run

1. Scrape (`run_ingestion_db_async.py`)
2. Descriptions (`run_description_backfill.py`)
3. **Reactivate returning jobs (this step)**
4. Cleanup (delete staged rows with no description), then promote

It must come **before** the cleanup. A returning job's staged row often has no description, because the
description step skips jobs already in production. If the cleanup runs first, it deletes the only
evidence that the job came back.

## Easiest way

If you can run commands on the agent service:
```
python run_reactivate_returning_jobs.py --dry-run    # preview
python run_reactivate_returning_jobs.py              # apply
```
It prints `Reactivated N returning jobs`. Put that line in the run summary.

## By hand in the database console

**1. Find the latest batch:**
```sql
SELECT batch_id, MAX(scraped_at) AS scraped_at, COUNT(*) AS rows
FROM jobs_staging GROUP BY batch_id ORDER BY MAX(scraped_at) DESC LIMIT 3;
```
Use the top `batch_id` below in place of `<BATCH>`. Check that its time matches tonight's scrape.

**2. Preview the count and a sample.** Changes nothing.
```sql
WITH seen AS (
    SELECT company_id, source_url, MAX(scraped_at) AS seen_at
    FROM jobs_staging
    WHERE batch_id = '<BATCH>' AND source_url IS NOT NULL AND btrim(source_url) <> ''
    GROUP BY company_id, source_url
)
SELECT COUNT(*) AS will_reactivate
FROM jobs j JOIN seen s ON s.company_id = j.company_id AND s.source_url = j.source_url
WHERE j.is_active = FALSE
  AND j.raw_text IS NOT NULL AND char_length(btrim(j.raw_text)) >= 100;
```
To see examples, replace `SELECT COUNT(*) AS will_reactivate` with
`SELECT j.id, j.title, j.source_url, j.scraped_at` and add `LIMIT 10`.

**3. Apply it in one transaction:**
```sql
BEGIN;
WITH seen AS (
    SELECT company_id, source_url, MAX(scraped_at) AS seen_at
    FROM jobs_staging
    WHERE batch_id = '<BATCH>' AND source_url IS NOT NULL AND btrim(source_url) <> ''
    GROUP BY company_id, source_url
)
UPDATE jobs j
SET is_active = TRUE, scraped_at = s.seen_at
FROM seen s
WHERE s.company_id = j.company_id AND s.source_url = j.source_url
  AND j.is_active = FALSE
  AND j.raw_text IS NOT NULL AND char_length(btrim(j.raw_text)) >= 100;
-- The console shows "UPDATE N". N should equal the preview count.
COMMIT;   -- or ROLLBACK if N doesn't match
```

**4. Report** `Reactivated N returning jobs` in the run summary.

## Rules

- Match on company **and** job link (`company_id` + `source_url`), in the **latest batch only**.
- Only reactivate jobs that already have a description in production (100+ characters).
- Count a job as returning whatever its staging review status is. Being in the scrape means the posting
  is live.
- Never change title, description, date posted, department or location here.
- Nobody has ever deactivated jobs by hand (confirmed 15 Oct), so every inactive job that reappears
  can be reactivated. If manual deactivation starts later, this step needs a guard first. Ask before
  applying.
- If the preview count looks unusually large (thousands), stop and ask before applying.
