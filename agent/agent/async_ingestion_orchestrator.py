"""
Async Ingestion Orchestrator — asyncio-based replacement for the sync
ThreadPoolExecutor model. Eliminates greenlet sync-to-async issues by
using native async/await throughout.

This module is a drop-in replacement for ingestion_orchestrator.py that
uses asyncio instead of ThreadPoolExecutor, and async Playwright instead
of sync Playwright.

Performance:
  - Sync model: one browser per worker thread, limited to ~10 threads
  - Async model: one shared browser, 1000s of concurrent page contexts
  - Async is lighter and avoids thread overhead entirely
  - Eliminates greenlet context-switching issues completely

Reliability fixes (2026-08-24, after a driver crash on the sync
pipeline — see career_scraper.py's module docstring for the full
incident writeup):
  - A company whose scrape hits a dead browser (ScraperBrowserDeadError)
    is no longer silently recorded as "0 jobs found". The shared
    browser is discarded and relaunched, and the company is retried
    once against the fresh browser before being given up on.
  - `browser_pool.get()` is now only called for companies that actually
    fall through to the Playwright scrape path — companies resolved
    via an ATS API never touch a browser at all.
  - Fixed a pre-existing bug: every `timing_log` entry recorded
    `company_name` as the literal string `"unknown"` instead of the
    actual company, because `process_company`'s return tuple never
    carried the name through to where the log entry was built. That
    made `per_company_timing` useless for tracing which company was
    slow or failing — exactly the kind of detail you'd want when
    diagnosing an incident like this one.
  - Per-company progress logging is sampled instead of printed for
    every single completion, for the same log-rate-limit reason as
    the sync orchestrator.
  - `FUTURE_TIMEOUT_SECONDS` raised from 50 to 100: with a scrape now
    allowed one retry after a dead-browser error (relaunch + a second
    full-length attempt, each up to `HARD_TIMEOUT_SECONDS` in
    async_career_scraper.py), the old 50s outer cap left almost no
    room for a legitimate retry to complete.
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable

from .ats_detector import detect_ats
from .ats_api import fetch_jobs
from .async_career_scraper import scrape_careers_page
from .async_browser_pool import AsyncBrowserPool
from .scraper_errors import ScraperBrowserDeadError
from .company_source import CompanySource
from .job_sink import JobSink

DEFAULT_MAX_WORKERS = 10
DEFAULT_SCRAPE_RETRIES = 2   # attempts per company against the career-scrape path
MAX_PROGRESS_LINES = 200     # roughly how many "[n/total] Scraped X" lines to print for the whole run
# Hard cap on how long a single company can take. Covers up to
# DEFAULT_SCRAPE_RETRIES attempts, each up to HARD_TIMEOUT_SECONDS (45s)
# in async_career_scraper.py, plus a buffer for browser relaunch.
FUTURE_TIMEOUT_SECONDS = 100


async def run(
    company_source: CompanySource,
    job_sink: JobSink,
    max_workers: int = DEFAULT_MAX_WORKERS,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Async version: loads companies, scrapes jobs concurrently with asyncio.

    Returns the same summary dict as the sync orchestrator.
    """
    # Use mutable containers to avoid nonlocal issues
    state = {
        "completed_count": 0,
        "ats_hit_count": 0,
        "scraped_count": 0,
        "failed_count": 0,
    }

    def progress(pct: float, msg: str):
        if progress_callback:
            progress_callback(pct, msg)
        else:
            print(f"[{int(pct*100):3d}%] {msg}")

    companies = company_source.load()
    total = len(companies)
    log_every = max(1, total // MAX_PROGRESS_LINES)
    progress(0.02, f"Loaded {total} companies.")

    all_jobs: list[dict] = []
    errors: list[str] = []
    timing_log: list[dict] = []

    browser_pool = AsyncBrowserPool()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async def scrape_with_retry(careers_url: str, domain: str, company_name: str) -> list[dict]:
        """Runs the Playwright fallback scrape. If the shared browser's
        driver connection has died, discards it and retries once with a
        freshly launched browser instead of leaving every other
        concurrent task sharing it silently broken too."""
        last_err = None
        for attempt in range(1, DEFAULT_SCRAPE_RETRIES + 1):
            browser = await browser_pool.get()
            try:
                return await scrape_careers_page(careers_url, domain, browser=browser)
            except ScraperBrowserDeadError as e:
                last_err = e
                print(f"[async_ingestion_orchestrator] Browser died while scraping {company_name} "
                      f"(attempt {attempt}/{DEFAULT_SCRAPE_RETRIES}) — relaunching and retrying.")
                await browser_pool.invalidate()
        raise RuntimeError(f"browser kept dying while scraping {careers_url}: {last_err}")

    async def process_company(company: dict):
        """Process one company; returns (name, job_rows, path, elapsed, error)."""
        name = company["company_name"]
        website = company["website"] or None
        started = datetime.now()

        try:
            ats_result = detect_ats(name, website)

            raw_jobs = []
            path_taken = "unknown"

            if ats_result.can_api and ats_result.token:
                raw_jobs = fetch_jobs(ats_result.ats, ats_result.token)
                path_taken = "ats_api"
            elif ats_result.careers_url:
                domain = _extract_domain(ats_result.careers_url)
                raw_jobs = await scrape_with_retry(ats_result.careers_url, domain, name)
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
            return name, job_rows, path_taken, elapsed, None

        except Exception as e:
            elapsed = (datetime.now() - started).total_seconds()
            return name, [], "error", elapsed, f"{name}: {e}"

    async def process_with_progress(company: dict):
        """Wrapper that updates progress and handles timeout."""
        name = company["company_name"]
        try:
            result = await asyncio.wait_for(
                process_company(company),
                timeout=FUTURE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            result = name, [], "timeout", 0.0, f"{name}: did not complete within {FUTURE_TIMEOUT_SECONDS}s"
        except Exception as e:
            result = name, [], "error", 0.0, f"{name}: {e}"

        state["completed_count"] += 1
        n = state["completed_count"]
        pct = 0.05 + 0.90 * (n / max(total, 1))
        if n % log_every == 0 or n == total:
            progress(pct, f"[{n}/{total}] Scraped {name}")

        return result

    try:
        # Process companies concurrently with a semaphore to limit concurrency
        semaphore = asyncio.Semaphore(max_workers)

        async def process_with_semaphore(company):
            async with semaphore:
                return await process_with_progress(company)

        results = await asyncio.gather(
            *[process_with_semaphore(c) for c in companies],
            return_exceptions=False
        )

        for name, job_rows, path_taken, elapsed, err in results:
            all_jobs.extend(job_rows)
            timing_log.append({
                "company_name": name,
                "path": path_taken,
                "elapsed_seconds": round(elapsed, 2),
                "jobs_found": len(job_rows),
            })

            if path_taken == "ats_api":
                state["ats_hit_count"] += 1
            elif path_taken == "career_scrape":
                state["scraped_count"] += 1
            else:
                state["failed_count"] += 1

            if err:
                errors.append(err)

    finally:
        await browser_pool.close()

    progress(0.97, f"Writing {len(all_jobs)} jobs to sink…")
    job_sink.write(all_jobs)
    progress(1.0, f"Done. {len(all_jobs)} jobs from {total} companies.")

    return {
        "companies_total":    total,
        "companies_ats_hit":  state["ats_hit_count"],
        "companies_scraped":  state["scraped_count"],
        "companies_failed":   state["failed_count"],
        "jobs_found":         len(all_jobs),
        "errors":             errors,
        "per_company_timing": timing_log,
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"
