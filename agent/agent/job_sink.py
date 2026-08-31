"""
Job Sink — where scraped job listings get written to.

Three real sinks today:
  - CSVJobSink: writes the job-listing display fields to a CSV. Used
    for local smoke tests (run_ingestion.py) — never by the Railway
    cron job.
  - PostgresJobSink: upserts straight into the `jobs` table. Superseded
    by StagingJobSink for the Railway cron job (kept around for local/
    manual runs that want to skip the staging review step entirely).
  - StagingJobSink: writes into `jobs_staging` instead, tagged with a
    batch_id, so a run can be auto-cleaned and/or manually reviewed
    (see backend/routes/staging.py) before it reaches `jobs`. This is
    what run_ingestion_db.py uses in production.

ingestion_orchestrator.py only ever calls `.write(jobs)`.

Normalized input row shape (from ingestion_orchestrator.py):
  {
    "company_name":         str,
    "job_title":            str,
    "department":           str,
    "location":             str,
    "apply_url":            str,
    "posted_at":            str,   # ISO date or "" if unknown
    "funding_round":        str,
    "funding_amount":       str,
    "funding_date":         str,
    "ats":                  str,
    "careers_url":          str,
    "source":               str,
    "scraped_at":           str,   # ISO timestamp of this ingestion run
    "description_snippet":  str,
  }
"""

import csv
import datetime
from abc import ABC, abstractmethod

OUTPUT_FIELDS = [
    "company_name", "job_title", "department", "location", "apply_url",
    "posted_at", "funding_round", "funding_amount", "funding_date",
    "ats", "careers_url", "source", "scraped_at", "description_snippet",
]


class JobSink(ABC):
    @abstractmethod
    def write(self, jobs: list[dict]) -> None:
        raise NotImplementedError


class CSVJobSink(JobSink):
    def __init__(self, path: str):
        self.path = path

    def write(self, jobs: list[dict]) -> None:
        with open(self.path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            for job in jobs:
                writer.writerow({k: job.get(k, "") for k in OUTPUT_FIELDS})


class PostgresJobSink(JobSink):
    """
    Upserts scraped jobs into the Postgres `jobs` table:
        jobs(id PK, company_id FK->companies.id, title, department,
             location, date_posted, source_url, raw_text, is_active,
             scraped_at)

    Requires a UNIQUE constraint on (company_id, source_url) — see the
    migration note in run_ingestion_db.py's deploy instructions. Without
    it, ON CONFLICT has no target and every run duplicates rows instead
    of updating them.

    Behavior:
      - INSERT ... ON CONFLICT (company_id, source_url) DO UPDATE:
        re-scraping the same job updates it in place rather than
        duplicating it.
      - Jobs previously active for a company but NOT present in this
        run's fresh scrape get is_active=False (closed) rather than
        deleted — a company whose scrape returned 0 jobs (e.g. site
        down) leaves its existing jobs untouched, since "0 jobs found"
        is ambiguous with "scrape failed" and we'd rather not mass-close
        real listings on a transient failure.
      - `--limit` runs only touch companies actually in that run's
        batch; every other company's jobs are left alone.
    """

    def __init__(self, connection):
        self.connection = connection

    def write(self, jobs: list[dict]) -> None:
        if not jobs:
            return

        cur = self.connection.cursor()
        try:
            company_names = list({j["company_name"] for j in jobs})
            cur.execute(
                "SELECT id, name FROM companies WHERE name = ANY(%s)",
                (company_names,),
            )
            name_to_id = {name: cid for cid, name in cur.fetchall()}

            skipped_unknown_company = 0
            seen_urls_by_company: dict[int, set[str]] = {}

            for job in jobs:
                company_id = name_to_id.get(job["company_name"])
                if company_id is None:
                    # Shouldn't happen — job came from a company the
                    # source itself loaded from this same table — but
                    # don't let one bad row kill the whole write.
                    skipped_unknown_company += 1
                    continue

                source_url = job.get("apply_url") or ""
                date_posted = _resolve_date_posted(
                    job.get("posted_at", ""), job.get("scraped_at", "")
                )

                cur.execute(
                    """
                    INSERT INTO jobs
                        (company_id, title, department, location,
                         source_url, date_posted, raw_text, is_active, scraped_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE, %s)
                    ON CONFLICT (company_id, source_url) DO UPDATE SET
                        title       = EXCLUDED.title,
                        department  = EXCLUDED.department,
                        location    = EXCLUDED.location,
                        date_posted = EXCLUDED.date_posted,
                        raw_text    = EXCLUDED.raw_text,
                        is_active   = TRUE,
                        scraped_at  = EXCLUDED.scraped_at
                    """,
                    (
                        company_id,
                        job.get("job_title") or "",
                        job.get("department") or None,
                        job.get("location") or None,
                        source_url,
                        date_posted,
                        job.get("description_snippet") or None,
                        job.get("scraped_at") or None,
                    ),
                )
                seen_urls_by_company.setdefault(company_id, set()).add(source_url)

            for company_id, urls in seen_urls_by_company.items():
                cur.execute(
                    """
                    UPDATE jobs
                    SET is_active = FALSE
                    WHERE company_id = %s
                      AND is_active = TRUE
                      AND source_url != ALL(%s)
                    """,
                    (company_id, list(urls)),
                )

            self.connection.commit()

            if skipped_unknown_company:
                print(
                    f"[PostgresJobSink] Skipped {skipped_unknown_company} job(s) — "
                    f"company name not found in companies table.",
                    flush=True,
                )
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cur.close()


def _resolve_date_posted(posted_at: str, scraped_at: str) -> str:
    """jobs.date_posted is NOT NULL, but posted_at comes back "" whenever
    a source doesn't expose a post date. Fall back to the scrape date
    rather than let the insert fail the whole batch."""
    if posted_at:
        return posted_at[:10]
    if scraped_at:
        return scraped_at[:10]
    return datetime.date.today().isoformat()


def _normalize_funding_stage(raw: str) -> str | None:
    """Light cleanup on the 'Last Funding Type' CSV column before it's
    stored in companies.funding_stage. Currently just trims and blanks
    out empty values — extend here if you want specific variants
    (e.g. 'Series A - II') collapsed to a canonical form."""
    value = (raw or "").strip()
    return value or None


class StagingJobSink(JobSink):
    """
    Writes scraped jobs into the `jobs_staging` landing table instead
    of straight into `jobs`, so a batch can be auto-cleaned and/or
    manually reviewed before it ever reaches live listings — see
    backend/routes/staging.py (POST .../clean, POST .../promote).

    Every row written by one `write()` call shares the same batch_id
    (a single uuid.uuid4(), generated by the caller — see
    run_ingestion_db.py — and passed into the constructor), so the
    whole run can be queried, cleaned, and promoted as a unit.

    Preserves the one piece of PostgresJobSink's behavior that simply
    redirecting inserts to jobs_staging would otherwise silently lose:
    closing out (is_active = FALSE) jobs that disappeared from a
    company's listings. That can't wait for review/promote — a posting
    that's genuinely gone from the company's careers page shouldn't
    stay "active" in search results just because nobody's reviewed
    this batch yet, and staging review is about *scrape data quality*
    (junk titles, dupes, thin content), not about whether a posting
    still exists. So StagingJobSink runs the exact same closeout
    PostgresJobSink did, directly against `jobs`, based on which
    source_urls were actually seen this run — regardless of what
    review_status those jobs_staging rows land in, and regardless of
    whether/when the batch ever gets promoted.

    Like PostgresJobSink, a company whose scrape returned 0 jobs this
    run is left out of closeout entirely (no seen_urls_by_company
    entry for it), so a transient scrape failure never mass-closes a
    company's real listings.

    No ON CONFLICT here, unlike PostgresJobSink — jobs_staging accumulates
    one row per scraped listing per run rather than deduping across runs;
    promote() is what applies (company_id, source_url) dedup when a batch
    is pushed into `jobs`.
    """

    def __init__(self, connection, batch_id: str):
        self.connection = connection
        self.batch_id = batch_id

    def write(self, jobs: list[dict]) -> None:
        if not jobs:
            return

        cur = self.connection.cursor()
        try:
            company_names = list({j["company_name"] for j in jobs})
            cur.execute(
                "SELECT id, name FROM companies WHERE name = ANY(%s)",
                (company_names,),
            )
            name_to_id = {name: cid for cid, name in cur.fetchall()}

            skipped_unknown_company = 0
            seen_urls_by_company: dict[int, set[str]] = {}

            for job in jobs:
                company_id = name_to_id.get(job["company_name"])
                if company_id is None:
                    # Shouldn't happen — job came from a company the
                    # source itself loaded from this same table — but
                    # don't let one bad row kill the whole write.
                    skipped_unknown_company += 1
                    continue

                source_url = job.get("apply_url") or ""
                date_posted = _resolve_date_posted(
                    job.get("posted_at", ""), job.get("scraped_at", "")
                )

                cur.execute(
                    """
                    INSERT INTO jobs_staging
                        (company_id, title, department, location,
                         source_url, date_posted, raw_text, scraped_at, batch_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        company_id,
                        job.get("job_title") or "",
                        job.get("department") or None,
                        job.get("location") or None,
                        source_url or None,
                        date_posted,
                        job.get("description_snippet") or None,
                        job.get("scraped_at") or None,
                        self.batch_id,
                    ),
                )
                # Seen this run regardless of what review status it lands
                # on below — closeout cares about presence on the
                # company's careers page, not scrape data quality.
                seen_urls_by_company.setdefault(company_id, set()).add(source_url)

            # Same closeout PostgresJobSink did, run directly against the
            # live `jobs` table — doesn't wait on staging review/promote.
            for company_id, urls in seen_urls_by_company.items():
                cur.execute(
                    """
                    UPDATE jobs
                    SET is_active = FALSE
                    WHERE company_id = %s
                      AND is_active = TRUE
                      AND source_url != ALL(%s)
                    """,
                    (company_id, list(urls)),
                )

            self.connection.commit()

            if skipped_unknown_company:
                print(
                    f"[StagingJobSink] Skipped {skipped_unknown_company} job(s) — "
                    f"company name not found in companies table.",
                    flush=True,
                )
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cur.close()