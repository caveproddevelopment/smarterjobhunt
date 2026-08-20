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
    "company_name":         str,
    "job_title":            str,
    "department":           str,
    "location":             str,
    "apply_url":            str,
    "posted_at":            str,   # ISO date or "" if unknown
    "funding_round":        str,
    "funding_amount":       str,
    "funding_date":         str,
    "ats":                  str,   # greenhouse | lever | ashby | workable | unknown
    "careers_url":          str,
    "source":               str,   # "ats_api" | "career_scrape"
    "scraped_at":           str,   # ISO timestamp of this ingestion run
    "description_snippet":  str,   # added 2026-08-19 — first N chars of cleaned JD text,
                                    # see agent/text_extract.py. Exists specifically so a
                                    # title-only search (e.g. "SAP S4HANA") can also match
                                    # against description content, not just the job title.
  }
"""

import csv
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


class DatasetJobSink(JobSink):
    """
    PLANNED — not yet implemented. Will write into the SJH.com job
    dataset/DB (MySQL `jobs` table) instead of a CSV. Left as a stub so
    the swap point is visible now.

    Expected eventual behavior: upsert by (company, apply_url) so a
    re-run doesn't create duplicate rows, and mark jobs no longer
    present in a fresh scrape as closed rather than deleting them.

    Schema note for description_snippet: whatever this becomes (MySQL or
    otherwise), the search-side change (matching a searched title against
    this field, not just job_title) needs to happen in the SJH.com/
    MyJobHunt search layer, which is a separate codebase from this
    ingestion agent — this sink only needs to store the field. If the
    eventual table is MySQL, a FULLTEXT index on description_snippet
    (not just an equality/LIKE match) is what makes that search usable
    at scale.
    """

    def __init__(self, connection):
        self.connection = connection

    def write(self, jobs: list[dict]) -> None:
        raise NotImplementedError(
            "DatasetJobSink is a planned stub — SJH.com will implement this "
            "once the jobs table schema (and dedup/upsert/closed-job logic) "
            "is finalized. Use CSVJobSink for now."
        )
