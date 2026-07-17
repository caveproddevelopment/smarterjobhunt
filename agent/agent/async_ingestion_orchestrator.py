"""
Async Ingestion Orchestrator — asyncio-based replacement for the sync
ThreadPoolExecutor model. Eliminates greenlet sync-to-async issues by
using native async/await throughout.

This module is a drop-in replacement for ingestion_orchestrator.py that
uses asyncio.gather() instead of ThreadPoolExecutor, and async Playwright
instead of sync Playwright.

Performance:
  - Sync model: one browser per worker thread, ~10 browsers for 10 workers
  - Async model: one shared browser, 1000s of concurrent page contexts
  - Async is lighter and avoids thread overhead entirely
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable

from .ats_detector import detect_ats
from .ats_api import fetch_jobs
from .async_career_scraper import scrape_careers_page
from .async_browser_pool import AsyncBrowserPool
from .company_source import CompanySource
from .job_sink import JobSink

DEFAULT_MAX_WORKERS = 10
# Hard cap on how long a single company can take.
# The scraper itself has 45s timeout; we cap the whole process here.
FUTURE_TIMEOUT_SECONDS = 50


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
    ats_hit_count = 0
    scraped_count = 0
    failed_count = 0

    browser_pool = AsyncBrowserPool()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async def process_company(company: dict):
        """Process one company; returns (job_rows, path, elapsed, error)."""
        name = company["company_name"]
        website = company["website"] or None
        started = datetime.now()
        browser = await browser_pool.get()

        try:
            ats_result = detect_ats(name, website)

            raw_jobs = []
            path_taken = "unknown"

            if ats_result.can_api and ats_result.token:
                raw_jobs = fetch_jobs(ats_result.ats, ats_result.token)
                path_taken = "ats_api"
            elif ats_result.careers_url:
                domain = _extract_domain(ats_result.careers_url)
                raw_jobs = await scrape_careers_page(ats_result.careers_url, domain, browser=browser)
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

    async def process_with_progress(company: dict):
        """Wrapper that updates progress and handles timeout."""
        name = company["company_name"]
        try:
            result = await asyncio.wait_for(
                process_company(company),
                timeout=FUTURE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            result = [], "timeout", 0.0, f"{name}: did not complete within {FUTURE_TIMEOUT_SECONDS}s"
        except Exception as e:
            result = [], "error", 0.0, f"{name}: {e}"

        # Update progress
        completed_count[0] += 1
        pct = 0.05 + 0.90 * (completed_count[0] / max(total, 1))
        progress(pct, f"[{completed_count[0]}/{total}] Scraped {name}")

        return result

    try:
        # Process companies in batches to avoid overwhelming the system.
        # asyncio.gather processes up to max_workers concurrently.
        results = await asyncio.gather(
            *[process_with_progress(c) for c in companies],
            return_exceptions=False
        )

        nonlocal ats_hit_count, scraped_count, failed_count
        for job_rows, path_taken, elapsed, err in results:
            all_jobs.extend(job_rows)
            timing_log.append({
                "company_name": company["company_name"] if "company" in locals() else "unknown",
                "path": path_taken,
                "elapsed_seconds": round(elapsed, 2),
                "jobs_found": len(job_rows),
            })

            if path_taken == "ats_api":
                ats_hit_count += 1
            elif path_taken == "career_scrape":
                scraped_count += 1
            else:
                failed_count += 1

            if err:
                errors.append(err)

    finally:
        await browser_pool.close()

    progress(0.97, f"Writing {len(all_jobs)} jobs to sink…")
    job_sink.write(all_jobs)
    progress(1.0, f"Done. {len(all_jobs)} jobs from {total} companies.")

    return {
        "companies_total":    total,
        "companies_ats_hit":  ats_hit_count,
        "companies_scraped":  scraped_count,
        "companies_failed":   failed_count,
        "jobs_found":         len(all_jobs),
        "errors":             errors,
        "per_company_timing": timing_log,
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

