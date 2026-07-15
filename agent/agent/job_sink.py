"""
Job Sink — where scraped job listings get written to.

Today: a CSV file, matching the job-listing display fields established
for SJH.com, minus "Match %" (that's computed at user-search time
against variants, not at ingestion time — this agent has no title
input at all) and minus contacts (that's the separate, on-demand V2
contact-finder step, not part of ingestion).

Later: a dataset/DB writer (the SJH.com job DB). Same interface either
way — ingestion_orchestrator.py only ever calls `.write(jobs)`.

Normalized output row shape:
  {
    "company_name":    str,
    "job_title":       str,
    "department":      str,
    "location":        str,
    "apply_url":       str,
    "posted_at":       str,   # ISO date or "" if unknown
    "funding_round":   str,
    "funding_amount":  str,
    "funding_date":    str,
    "ats":             str,   # greenhouse | lever | ashby | workable | unknown
    "careers_url":     str,
    "source":          str,   # "ats_api" | "career_scrape"
    "scraped_at":      str,   # ISO timestamp of this ingestion run
  }
"""

import csv
from abc import ABC, abstractmethod

OUTPUT_FIELDS = [
    "company_name", "job_title", "department", "location", "apply_url",
    "posted_at", "funding_round", "funding_amount", "funding_date",
    "ats", "careers_url", "source", "scraped_at",
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


class DatasetJobSink(JobSink):
    """
    PLANNED — not yet implemented. Will write into the SJH.com job
    dataset/DB (MySQL `jobs` table) instead of a CSV. Left as a stub so
    the swap point is visible now.

    Expected eventual behavior: upsert by (company, apply_url) so a
    re-run doesn't create duplicate rows, and mark jobs no longer
    present in a fresh scrape as closed rather than deleting them.
    """

    def __init__(self, connection):
        self.connection = connection

    def write(self, jobs: list[dict]) -> None:
        raise NotImplementedError(
            "DatasetJobSink is a planned stub — SJH.com will implement this "
            "once the jobs table schema (and dedup/upsert/closed-job logic) "
            "is finalized. Use CSVJobSink for now."
        )


# ---------------------------------------------------------------------------
# Funding round string (from the company CSV / Crunchbase-style export) ->
# the `funding_stage` enum the Postgres `companies` table expects.
# ---------------------------------------------------------------------------
_FUNDING_STAGE_MAP = {
    "pre-seed": "seed",
    "seed": "seed",
    "series a": "series_a",
    "series b": "series_b",
    "series c": "series_c_plus",
    "series d": "series_c_plus",
    "series e": "series_c_plus",
    "series f": "series_c_plus",
    "ipo": "public",
    "post-ipo": "public",
    "public": "public",
    "bootstrapped": "bootstrapped",
    "self-funded": "bootstrapped",
}


def _normalize_funding_stage(funding_round: str) -> str:
    return _FUNDING_STAGE_MAP.get((funding_round or "").strip().lower(), "unknown")


class PostgresJobSink(JobSink):
    """
    Writes scraped jobs straight into the SmarterJobHunt Postgres DB
    (the `companies` + `jobs` tables from db/schema.sql), so the backend
    API — and the frontend search — see new listings immediately after
    an ingestion run.

    Upserts by (company name) for companies and by (company_id,
    source_url) for jobs, matching the unique indexes added to
    schema.sql. Jobs that belonged to a scraped company in a previous
    run but weren't seen in this run are marked is_active = false
    (closed) rather than deleted, so history/match data isn't lost.

    `connection` is any psycopg2 connection (e.g. from
    `psycopg2.connect(os.environ["DATABASE_URL"])`). The sink commits
    once at the end of `write()`.
    """

    def __init__(self, connection):
        self.connection = connection

    def write(self, jobs: list[dict]) -> None:
        if not jobs:
            return

        cur = self.connection.cursor()
        try:
            company_ids: dict[str, int] = {}
            seen_source_urls: dict[int, set[str]] = {}

            for job in jobs:
                company_name = (job.get("company_name") or "").strip()
                if not company_name:
                    continue

                if company_name not in company_ids:
                    cur.execute(
                        """
                        INSERT INTO companies (name, website, funding_stage, funding_amount, funding_date)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (name) DO UPDATE SET
                            website        = EXCLUDED.website,
                            funding_stage  = EXCLUDED.funding_stage,
                            funding_amount = EXCLUDED.funding_amount,
                            funding_date   = EXCLUDED.funding_date
                        RETURNING id
                        """,
                        (
                            company_name,
                            job.get("careers_url") or None,
                            _normalize_funding_stage(job.get("funding_round", "")),
                            job.get("funding_amount") or None,
                            job.get("funding_date") or None,
                        ),
                    )
                    company_ids[company_name] = cur.fetchone()[0]

                company_id = company_ids[company_name]
                source_url = (job.get("apply_url") or "").strip() or None
                seen_source_urls.setdefault(company_id, set())
                if source_url:
                    seen_source_urls[company_id].add(source_url)

                cur.execute(
                    """
                    INSERT INTO jobs (company_id, title, department, location, date_posted, source_url, raw_text, is_active, scraped_at)
                    VALUES (%s, %s, %s, %s, COALESCE(NULLIF(%s, '')::date, CURRENT_DATE), %s, %s, true, now())
                    ON CONFLICT (company_id, source_url) WHERE source_url IS NOT NULL
                    DO UPDATE SET
                        title       = EXCLUDED.title,
                        department  = EXCLUDED.department,
                        location    = EXCLUDED.location,
                        is_active   = true,
                        scraped_at  = now()
                    """,
                    (
                        company_id,
                        job.get("job_title", ""),
                        job.get("department") or None,
                        job.get("location") or None,
                        job.get("posted_at", ""),
                        source_url,
                        None,
                    ),
                )

            # Close out jobs at scraped companies that no longer appeared in this run.
            for company_id, urls in seen_source_urls.items():
                if urls:
                    cur.execute(
                        """
                        UPDATE jobs SET is_active = false
                        WHERE company_id = %s AND is_active = true AND source_url != ALL(%s)
                        """,
                        (company_id, list(urls)),
                    )
                else:
                    cur.execute(
                        "UPDATE jobs SET is_active = false WHERE company_id = %s AND is_active = true",
                        (company_id,),
                    )

            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        finally:
            cur.close()
