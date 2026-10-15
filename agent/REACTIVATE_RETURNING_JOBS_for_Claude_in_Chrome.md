# Change to the standing cleanup/promote script: reactivate returning jobs

**For:** Claude in Chrome, which runs the standing jobs_staging cleanup and promote for JobBeggar.
**Approved by:** Monte, 2026-10-15.

## The problem
When a job disappears from a company's careers page, the scrape marks it
`is_active = FALSE` in `jobs`. When the same job (same company, same
`source_url`) shows up again in a later scrape, the standing rule "existing jobs
are never overwritten" leaves it inactive forever. On 14 Oct, 1,268 inactive
jobs were back in the scrape, which means they're open again but hidden from
JobBeggar search.

## The change
Add one new step. **It only flips `is_active` back to TRUE and updates
`scraped_at`.** Title, description, location, `date_posted` and `first_seen_at`
are not touched, so the "never overwrite existing jobs" rule still holds for
everything else.

### Where it goes in the run
Right after the scrape and the description backfill, and **before** the step
that deletes rows with no description. A returning job's staged row may have
no description (the backfill skips jobs that are already in `jobs`), so if the
delete runs first, the evidence that the job came back is gone.

New order:
1. `run_ingestion_db_async.py` (scrape, core info only). Note the Batch ID it prints.
2. `run_description_backfill.py` (descriptions for the batch's new jobs).
3. **Reactivate returning jobs (this step).**
4. Existing cleanup: back up and delete empty-description rows, junk rules.
5. Existing promote of new jobs.

### Step 3: preview first, then apply
```sql
-- Preview: how many inactive jobs reappeared in this batch?
SELECT COUNT(*) AS returning_jobs
FROM jobs j
WHERE j.is_active = FALSE
  AND j.raw_text IS NOT NULL AND btrim(j.raw_text) <> ''
  AND EXISTS (
      SELECT 1 FROM jobs_staging s
      WHERE s.batch_id = '<BATCH_ID>'
        AND s.company_id = j.company_id
        AND s.source_url = j.source_url);

-- Apply (one transaction):
BEGIN;
UPDATE jobs j
SET is_active = TRUE,
    scraped_at = now()
FROM (SELECT DISTINCT company_id, source_url
      FROM jobs_staging
      WHERE batch_id = '<BATCH_ID>' AND source_url IS NOT NULL) s
WHERE j.company_id = s.company_id
  AND j.source_url = s.source_url
  AND j.is_active = FALSE
  AND j.raw_text IS NOT NULL AND btrim(j.raw_text) <> '';
-- Check the row count matches the preview, then:
COMMIT;
```

### Rules
- **Only this batch.** Match on `batch_id`, `company_id` and `source_url`
  together, never on the title.
- **Only jobs that already have a description.** That's the
  `raw_text IS NOT NULL` condition, which keeps the existing rule that live jobs
  must have a description.
- **Never reactivate a job someone deactivated on purpose** (for example junk
  removed by hand). If there's a list or marker for manually removed jobs,
  exclude it with `AND j.id NOT IN (...)`. If you're unsure whether any exist,
  ask Monte before applying.
- **Report the count** in the run summary, as "Reactivated N returning jobs",
  next to the insert count.
- `date_posted` is deliberately left alone, so a reactivated job doesn't show up
  as "new" in search or the recruiter feed.

### Sanity checks after applying
```sql
-- Should be 0: nothing reactivated without a description
SELECT COUNT(*) FROM jobs WHERE is_active AND (raw_text IS NULL OR btrim(raw_text) = '');
-- Active count went up by the reactivated number
SELECT COUNT(*) FROM jobs WHERE is_active;
```

### Or run the script (same rules)
If you can run commands on the agent service, `run_reactivate_returning_jobs.py`
does step 3's preview and apply for the latest batch, in one transaction:
```
python run_reactivate_returning_jobs.py --dry-run            # preview count + 10 sample jobs
python run_reactivate_returning_jobs.py                      # apply; prints "Reactivated N returning jobs"
python run_reactivate_returning_jobs.py --batch-id <BATCH_ID>
```
It was confirmed on 15 Oct that no jobs have been deactivated by hand, so there
is no exclusion list today. If that changes, add the exclusion before running.
