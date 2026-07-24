"""
Ingestion Orchestrator — SJH.com's nightly batch agent (proof of
concept). This is deliberately the *only* thing this agent does:

    for every company -> detect its ATS -> pull every job currently
    posted (via the ATS's public API, or a Playwright fallback scrape
    of the careers page) -> hand the raw listings to a JobSink.

What this agent explicitly does NOT do (by design, not by omission):
  - No job-title input, no keyword expansion, no match scoring.
    Matching against a user's searched title happens later, at search
    time, against whatever's already in the job DB. Baking a title
    into ingestion would mean re-scraping the same companies once per
    title instead of once per company.
  - No Apollo / contact lookups. That's a separate, on-demand step in
    both MyJobHunt and (eventually) SJH.com's V2 — never bundled into
    the batch job that runs against 1000+ companies unconditionally.

Same concurrency model as MyJobHunt's job_orchestrator.py: companies
processed in a thread pool, one persistent Playwright browser per
worker thread (via BrowserPool) instead of one browser launch per
company.

TIMEOUT FIX (2026-07-17):
Added fut.result(timeout=...) at the orchestrator level to prevent
stuck threads from blocking the entire batch when a future hangs
(e.g., due to Playwright greenlet issues). Companies that time out
are skipped and logged as errors, but the batch continues.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Optional, Callable
import threading

from .ats_detector import detect_ats
from .ats_api import fetch_jobs
from .career_scraper import scrape_careers_page
from .browser_pool import BrowserPool
from .company_source import CompanySource
from .job_sink import JobSink

DEFAULT_MAX_WORKERS = 10
# Timeout per company at the thread pool level. Should be >= the max time
# a single company can take (ATS API call + Playwright scrape + processing).
# The scraper itself has a 45s hard timeout; we add 30s buffer here.
FUTURE_TIMEOUT_SECONDS = 120


def run(
    company_source: CompanySource,
    job_sink: JobSink,
    max_workers: int = DEFAULT_MAX_WORKERS,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Loads companies from `company_source`, scrapes every job at every
    company, writes the results to `job_sink`.

    Returns a run summary dict:
      {
        "companies_total":     int,
        "companies_ats_hit":   int,   # resolved via a supported ATS API
        "companies_scraped":   int,   # fell back to Playwright scrape
        "companies_failed":    int,   # no jobs found, error, or unknown ATS
        "jobs_found":          int,
        "errors":              list[str],
        "per_company_timing":  list[dict],  # for the batch-size speed test
      }
    """
    progress_lock = threading.Lock()
    completed_count = [0]

    def progress(pct: float, msg: str):
        if progress_callback:
            progress_callback(pct, msg)
        else:
            print(f"[{int(pct*100):3d}%] {msg}")

    companies = company_source.load()
    total = len(companies)
    progress(0.02, f"Loaded {total} companies.")

    all_jobs: list[dict] = []
    errors: list[str] = []
    timing_log: list[dict] = []
    ats_hit_count = [0]
    scraped_count = [0]
    failed_count = [0]

    browser_pool = BrowserPool()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def process_company(company: dict) -> tuple[list[dict], str, float, Optional[str]]:
        """Returns (job_rows, path_taken, elapsed_seconds, error_or_none)."""
        name = company["company_name"]
        website = company["website"] or None
        started = datetime.now()
        browser = browser_pool.get()

        try:
            ats_result = detect_ats(name, website)

            raw_jobs = []
            path_taken = "unknown"

            if ats_result.can_api and ats_result.token:
                raw_jobs = fetch_jobs(ats_result.ats, ats_result.token)
                path_taken = "ats_api"
            elif ats_result.careers_url:
                domain = _extract_domain(ats_result.careers_url)
                raw_jobs = scrape_careers_page(ats_result.careers_url, domain, browser=browser)
                path_taken = "career_scrape"

            elapsed = (datetime.now() - started).total_seconds()

            job_rows = [
                {
                    "company_name":   name,
                    "job_title":      job.get("title", ""),
                    "department":     job.get("department", ""),
                    "location":       job.get("location", ""),
                    "apply_url":      job.get("apply_url", ""),
                    "posted_at":      job.get("posted_at", ""),
                    "funding_round":  company["funding_round"],
                    "funding_amount": company["funding_amount"],
                    "funding_date":   company["funding_date"],
                    "ats":            ats_result.ats,
                    "careers_url":    ats_result.careers_url or "",
                    "source":         path_taken,
                    "scraped_at":     run_ts,
                }
                for job in raw_jobs
            ]
            return job_rows, path_taken, elapsed, None

        except Exception as e:
            elapsed = (datetime.now() - started).total_seconds()
            return [], "error", elapsed, f"{name}: {e}"

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futures = {ex.submit(process_company, c): c for c in companies}

            for fut in as_completed(futures):
                company = futures[fut]
                name = company["company_name"]

                with progress_lock:
                    completed_count[0] += 1
                    pct = 0.05 + 0.90 * (completed_count[0] / max(total, 1))
                    progress(pct, f"[{completed_count[0]}/{total}] Scraped {name}")

                try:
                    # TIMEOUT FIX: prevent hung threads from blocking the batch.
                    # If a future doesn't complete within FUTURE_TIMEOUT_SECONDS,
                    # TimeoutError is raised and we skip it.
                    job_rows, path_taken, elapsed, err = fut.result(timeout=FUTURE_TIMEOUT_SECONDS)
                except TimeoutError:
                    job_rows, path_taken, elapsed, err = [], "timeout", 0.0, f"{name}: did not complete within {FUTURE_TIMEOUT_SECONDS}s (possible Playwright hang)"
                except Exception as e:
                    job_rows, path_taken, elapsed, err = [], "error", 0.0, f"{name}: {e}"

                all_jobs.extend(job_rows)
                timing_log.append({
                    "company_name": name,
                    "path": path_taken,
                    "elapsed_seconds": round(elapsed, 2),
                    "jobs_found": len(job_rows),
                })

                if path_taken == "ats_api":
                    ats_hit_count[0] += 1
                elif path_taken == "career_scrape":
                    scraped_count[0] += 1
                else:
                    failed_count[0] += 1

                if err:
                    errors.append(err)
    finally:
        browser_pool.close_all()

    progress(0.97, f"Writing {len(all_jobs)} jobs to sink…")
    job_sink.write(all_jobs)
    progress(1.0, f"Done. {len(all_jobs)} jobs from {total} companies.")

    return {
        "companies_total":    total,
        "companies_ats_hit":  ats_hit_count[0],
        "companies_scraped":  scraped_count[0],
        "companies_failed":   failed_count[0],
        "jobs_found":         len(all_jobs),
        "errors":             errors,
        "per_company_timing": timing_log,
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

