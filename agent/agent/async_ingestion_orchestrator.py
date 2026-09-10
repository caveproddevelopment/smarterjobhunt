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

Reliability fix (2026-09-10, after a 35+ minute full-pipeline freeze
with no log output at all, near the end of a 5501-company run):
  - `detect_ats()` and `fetch_jobs()` are synchronous, `requests`-based
    functions. They were being called directly inside `process_company`
    (an async function) with no `await` and no thread offload. A plain
    function call like that never yields control back to the event
    loop — so when one of them got stuck (most likely DNS resolution
    hanging past `requests`' own `timeout=`, which does not bound the
    DNS step), it froze the *entire* event loop, not just that one
    task. That's why every concurrent worker stopped logging at once,
    and why neither the 45s hard timeout in async_career_scraper.py
    nor FUTURE_TIMEOUT_SECONDS below ever fired: both depend on the
    loop being free to check elapsed time between awaits, which it
    wasn't. Both calls are now run via `asyncio.to_thread()` so a
    stuck call strands only its own worker thread; the event loop —
    and every other in-flight company — keeps moving, and
    FUTURE_TIMEOUT_SECONDS can now actually do its job.

Batching + incremental writes (2026-09-10, same incident): previously
the entire company list was scraped in one asyncio.gather() and
job_sink.write() was called exactly once, after every company
finished. A run that died at 94% — for any reason — had written
*nothing* to jobs_staging. Companies are now processed in sequential
chunks of `batch_size` (default 500), and job_sink.write() is called
once per chunk, so a run that dies partway through has already
committed every earlier chunk. The shared browser is also recycled
between chunks (async_browser_pool.py's docstring flagged this as a
safe, not-yet-implemented option for exactly this reason — a
multi-hour run no longer keeps one Chromium process alive the whole
time). See run_ingestion_db_async.py's matching `os._exit()` fix and
--clear-staging flag flip — batching and incremental writes are far
less useful if jobs_staging still gets wiped on the next scheduled run
before anyone's reviewed it, or if a leaked thread still hangs the
process at exit despite every chunk having saved successfully.
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
DEFAULT_BATCH_SIZE = 500     # companies processed, then written to job_sink, per sequential chunk
MAX_PROGRESS_LINES = 200     # roughly how many "[n/total] Scraped X" lines to print for the whole run
# Hard cap on how long a single company can take. Covers up to
# DEFAULT_SCRAPE_RETRIES attempts, each up to HARD_TIMEOUT_SECONDS (45s)
# in async_career_scraper.py, plus a buffer for browser relaunch.
FUTURE_TIMEOUT_SECONDS = 100


async def run(
    company_source: CompanySource,
    job_sink: JobSink,
    max_workers: int = DEFAULT_MAX_WORKERS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_callback: Optional[Callable] = None,
) -> dict:
    """
    Async version: loads companies, scrapes jobs concurrently with asyncio,
    in sequential chunks of `batch_size` companies at a time.

    `batch_size` (default 500): companies are split into consecutive
    chunks; each chunk is scraped with up to `max_workers` concurrent
    tasks, then written to `job_sink` immediately, before the next chunk
    starts. Set this >= the total company count to reproduce the old
    one-shot-at-the-end behavior. The shared browser is recycled between
    chunks (closed and relaunched fresh) — see the module docstring.

    Returns a run summary dict:
      {
        "companies_total":     int,
        "companies_ats_hit":   int,   # resolved via a supported ATS API
        "companies_scraped":   int,   # fell back to Playwright scrape
        "companies_failed":    int,   # no jobs found, error, or unknown ATS
        "companies_timed_out": int,   # abandoned after FUTURE_TIMEOUT_SECONDS
        "jobs_found":          int,
        "errors":              list[str],
        "per_company_timing":  list[dict],
      }
    """
    state = {
        "completed_count": 0,
        "ats_hit_count": 0,
        "scraped_count": 0,
        "failed_count": 0,
        "timed_out_count": 0,
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

    all_errors: list[str] = []
    all_timing_log: list[dict] = []
    total_jobs_written = 0

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
            # detect_ats() and fetch_jobs() are synchronous (requests-based)
            # calls. Run them on a worker thread rather than inline, so a
            # slow/hung DNS lookup or connection can't freeze the whole
            # event loop — see the 2026-09-10 note in the module docstring.
            ats_result = await asyncio.to_thread(detect_ats, name, website)

            raw_jobs = []
            path_taken = "unknown"

            if ats_result.can_api and ats_result.token:
                raw_jobs = await asyncio.to_thread(fetch_jobs, ats_result.ats, ats_result.token)
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
                    "description_snippet": job.get("description_snippet", ""),
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
            print(f"[async_ingestion_orchestrator] STUCK: {name} did not complete within "
                  f"{FUTURE_TIMEOUT_SECONDS}s — abandoning it and moving on to the rest of the batch.")
            result = name, [], "timeout", 0.0, f"{name}: did not complete within {FUTURE_TIMEOUT_SECONDS}s"
        except Exception as e:
            result = name, [], "error", 0.0, f"{name}: {e}"

        state["completed_count"] += 1
        n = state["completed_count"]
        pct = 0.05 + 0.90 * (n / max(total, 1))
        if n % log_every == 0 or n == total:
            progress(pct, f"[{n}/{total}] Scraped {name}")

        return result

    chunks = [companies[i:i + batch_size] for i in range(0, total, batch_size)]
    num_chunks = len(chunks)

    try:
        semaphore = asyncio.Semaphore(max_workers)

        async def process_with_semaphore(company):
            async with semaphore:
                return await process_with_progress(company)

        for chunk_idx, chunk in enumerate(chunks, start=1):
            progress(
                0.05 + 0.90 * (state["completed_count"] / max(total, 1)),
                f"Starting batch {chunk_idx}/{num_chunks} ({len(chunk)} companies)…"
            )

            results = await asyncio.gather(
                *[process_with_semaphore(c) for c in chunk],
                return_exceptions=False
            )

            chunk_jobs: list[dict] = []
            for name, job_rows, path_taken, elapsed, err in results:
                chunk_jobs.extend(job_rows)
                all_timing_log.append({
                    "company_name": name,
                    "path": path_taken,
                    "elapsed_seconds": round(elapsed, 2),
                    "jobs_found": len(job_rows),
                })

                if path_taken == "ats_api":
                    state["ats_hit_count"] += 1
                elif path_taken == "career_scrape":
                    state["scraped_count"] += 1
                elif path_taken == "timeout":
                    state["timed_out_count"] += 1
                else:
                    state["failed_count"] += 1

                if err:
                    all_errors.append(err)

            progress(
                0.05 + 0.90 * (state["completed_count"] / max(total, 1)),
                f"Batch {chunk_idx}/{num_chunks}: writing {len(chunk_jobs)} job(s) to sink…"
            )
            job_sink.write(chunk_jobs)
            total_jobs_written += len(chunk_jobs)

            # Recycle the shared browser between chunks so a long multi-batch
            # run doesn't keep one Chromium process alive (and accumulating
            # memory) for the whole run — see async_browser_pool.py's
            # docstring. No tasks are in flight here (the gather() above has
            # already resolved), so this is always safe. Skipped after the
            # last chunk; the `finally` below closes it for good.
            if chunk_idx < num_chunks:
                await browser_pool.invalidate()

    finally:
        await browser_pool.close()

    timed_out_note = f" ({state['timed_out_count']} timed out)" if state["timed_out_count"] else ""
    progress(1.0, f"Done. {total_jobs_written} jobs from {total} companies "
                  f"across {num_chunks} batch(es){timed_out_note}.")

    return {
        "companies_total":     total,
        "companies_ats_hit":   state["ats_hit_count"],
        "companies_scraped":   state["scraped_count"],
        "companies_failed":    state["failed_count"],
        "companies_timed_out": state["timed_out_count"],
        "jobs_found":          total_jobs_written,
        "errors":              all_errors,
        "per_company_timing":  all_timing_log,
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"