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

Reliability fixes (2026-08-24, after a driver crash ~94% through a
1923-company run — see career_scraper.py and browser_pool.py for the
underlying fixes):
  - A company whose scrape hits a dead browser (ScraperBrowserDeadError)
    no longer gets silently recorded as "0 jobs found" while every
    other company on that thread quietly fails the same way for the
    rest of the run. The thread's browser is discarded and relaunched,
    and the company is retried once against the fresh browser before
    being given up on.
  - `browser_pool.get()` is now only called for companies that actually
    fall through to the Playwright scrape path — companies resolved via
    an ATS API never touch a browser at all, so a thread whose first
    several companies are all ATS-API hits no longer launches a browser
    it doesn't need.
  - Per-company progress logging is sampled instead of printed for
    every single completion. Printing one line per company across 10
    concurrent workers was fast enough to trip Railway's 500 logs/sec
    platform cap (1358 dropped log lines on the run that crashed) — the
    full per-company detail is still captured in the returned
    `per_company_timing` and `errors` lists regardless of what gets
    printed to the console.

Watchdog fix (2026-09-02, run stuck at ~94%/990-1000 every time): the
actual root cause was an unbounded BeautifulSoup parse in
text_extract.py (fixed there — see that module's docstring), but this
loop had no defense against *any* single company running away, from any
cause. It used `as_completed()` over every submitted future, which only
finishes once every future is done — one permanently stuck company
therefore blocked the whole batch forever, with no log line and nothing
to tell you which company it was.

This is now a bounded `wait()` loop instead: any company still running
past `COMPANY_HARD_TIMEOUT_SECONDS` gets logged by name and abandoned —
counted as failed/timed-out and excluded from further waiting — so the
rest of the batch keeps going and the run always finishes. The abandoned
task's OS thread isn't forcibly killed (Python can't do that to a
running thread) and may keep running in the background; the executor is
shut down with `wait=False` so we don't block on it either. See
run_ingestion_db.py's `__main__` block for the matching fix that forces
the process to actually exit afterward, since Python's
concurrent.futures.thread module joins every worker thread it ever
created at normal interpreter shutdown regardless of shutdown(wait=...).

COMPANY_HARD_TIMEOUT_SECONDS is deliberately generous (not tight): a
legitimately large company on the Workable ATS path can make one extra
HTTP request per open posting (see ats_api.py's _fetch_workable) with no
overall cap of its own, so a company with a couple hundred real postings
can legitimately take a while. This watchdog is a backstop against a
company that's actually stuck, not a performance tuning knob — set it
lower only if you've confirmed your slowest legitimate company finishes
well under it.
"""

from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from typing import Optional, Callable
import threading
import time

from .ats_detector import detect_ats
from .ats_api import fetch_jobs
from .career_scraper import scrape_careers_page
from .browser_pool import BrowserPool
from .scraper_errors import ScraperBrowserDeadError
from .company_source import CompanySource
from .job_sink import JobSink

DEFAULT_MAX_WORKERS = 10
DEFAULT_SCRAPE_RETRIES = 2  # attempts per company against the career-scrape path
MAX_PROGRESS_LINES = 200    # roughly how many "[n/total] Scraped X" lines to print for the whole run
COMPANY_HARD_TIMEOUT_SECONDS = 150  # a company running longer than this is abandoned, logged, and skipped
WATCHDOG_POLL_SECONDS = 5           # how often we check pending companies against the hard timeout


def run(
    company_source: CompanySource,
    job_sink: JobSink,
    max_workers: int = DEFAULT_MAX_WORKERS,
    progress_callback: Optional[Callable] = None,
    fetch_descriptions: bool = True,
) -> dict:
    """
    Loads companies from `company_source`, scrapes every job at every
    company, writes the results to `job_sink`.

    `fetch_descriptions` (added 2026-08-19): when True (default), each
    job row gets a description_snippet — see ats_api.py and
    career_scraper.py module docstrings for the real per-job request/
    page-load cost this adds, which varies a lot by ATS. Set False to
    reproduce the pre-2026-08-19 behavior exactly (title/link only, no
    added cost) — useful for an apples-to-apples timing comparison
    against the existing batch-size speed test numbers before deciding
    whether to enable this by default.

    Returns a run summary dict:
      {
        "companies_total":     int,
        "companies_ats_hit":   int,   # resolved via a supported ATS API
        "companies_scraped":   int,   # fell back to Playwright scrape
        "companies_failed":    int,   # no jobs found, error, or unknown ATS
        "companies_timed_out": int,   # abandoned after COMPANY_HARD_TIMEOUT_SECONDS — see module docstring
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
    log_every = max(1, total // MAX_PROGRESS_LINES)
    progress(0.02, f"Loaded {total} companies.")

    all_jobs: list[dict] = []
    errors: list[str] = []
    timing_log: list[dict] = []
    ats_hit_count = [0]
    scraped_count = [0]
    failed_count = [0]
    timed_out_count = [0]

    browser_pool = BrowserPool()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def scrape_with_retry(careers_url: str, domain: str, company_name: str) -> list[dict]:
        """Runs the Playwright fallback scrape. If the shared browser's
        driver connection has died, discards it and retries once with a
        freshly launched browser instead of leaving the rest of this
        thread's queue silently broken (see module docstring)."""
        last_err = None
        for attempt in range(1, DEFAULT_SCRAPE_RETRIES + 1):
            browser = browser_pool.get()
            try:
                return scrape_careers_page(careers_url, domain, browser=browser, fetch_descriptions=fetch_descriptions)
            except ScraperBrowserDeadError as e:
                last_err = e
                print(f"[ingestion_orchestrator] Browser died while scraping {company_name} "
                      f"(attempt {attempt}/{DEFAULT_SCRAPE_RETRIES}) — relaunching and retrying.")
                browser_pool.invalidate()
        raise RuntimeError(f"browser kept dying while scraping {careers_url}: {last_err}")

    def process_company(company: dict) -> tuple[list[dict], str, float, Optional[str]]:
        """Returns (job_rows, path_taken, elapsed_seconds, error_or_none)."""
        name = company["company_name"]
        website = company["website"] or None
        started = datetime.now()

        try:
            ats_result = detect_ats(name, website)

            raw_jobs = []
            path_taken = "unknown"

            if ats_result.can_api and ats_result.token:
                raw_jobs = fetch_jobs(ats_result.ats, ats_result.token, fetch_descriptions=fetch_descriptions)
                path_taken = "ats_api"
            elif ats_result.careers_url:
                domain = _extract_domain(ats_result.careers_url)
                raw_jobs = scrape_with_retry(ats_result.careers_url, domain, name)
                path_taken = "career_scrape"

            elapsed = (datetime.now() - started).total_seconds()

            job_rows = [
                {
                    "company_name":        name,
                    "job_title":           job.get("title", ""),
                    "department":          job.get("department", ""),
                    "location":            job.get("location", ""),
                    "apply_url":           job.get("apply_url", ""),
                    "posted_at":           job.get("posted_at", ""),
                    "funding_round":       company["funding_round"],
                    "funding_amount":      company["funding_amount"],
                    "funding_date":        company["funding_date"],
                    "ats":                 ats_result.ats,
                    "careers_url":         ats_result.careers_url or "",
                    "description_snippet": job.get("description_snippet", ""),
                    "source":         path_taken,
                    "scraped_at":     run_ts,
                }
                for job in raw_jobs
            ]
            return job_rows, path_taken, elapsed, None

        except Exception as e:
            elapsed = (datetime.now() - started).total_seconds()
            return [], "error", elapsed, f"{name}: {e}"

    def _record_result(name: str, job_rows, path_taken: str, elapsed: float, err: Optional[str]):
        """Shared bookkeeping for a company that actually finished (normally
        or with an ordinary error) — pulled out of the wait loop below so
        the timed-out branch can't drift out of sync with it."""
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
        elif path_taken == "timeout":
            timed_out_count[0] += 1
        else:
            failed_count[0] += 1
        if err:
            errors.append(err)

    try:
        ex = ThreadPoolExecutor(max_workers=max_workers)
        try:
            submitted_at = {}
            futures = {}
            for c in companies:
                fut = ex.submit(process_company, c)
                futures[fut] = c
                submitted_at[fut] = time.monotonic()

            pending = set(futures)
            abandoned = set()

            while pending:
                done, pending = wait(pending, timeout=WATCHDOG_POLL_SECONDS, return_when=FIRST_COMPLETED)

                for fut in done:
                    company = futures[fut]
                    name = company["company_name"]

                    try:
                        job_rows, path_taken, elapsed, err = fut.result()
                    except Exception as e:
                        job_rows, path_taken, elapsed, err = [], "error", 0.0, f"{name}: {e}"

                    with progress_lock:
                        completed_count[0] += 1
                        n = completed_count[0]
                        pct = 0.05 + 0.90 * (n / max(total, 1))
                        if n % log_every == 0 or n == total:
                            progress(pct, f"[{n}/{total}] Scraped {name}")

                    _record_result(name, job_rows, path_taken, elapsed, err)

                # Anything left in `pending` is still running — check whether
                # any of it has overstayed COMPANY_HARD_TIMEOUT_SECONDS. We
                # can't force-kill a running thread, so "abandon" just means
                # we stop waiting on it and let the batch move on; its result
                # (if it ever finishes) is discarded.
                now = time.monotonic()
                newly_abandoned = [
                    fut for fut in pending
                    if now - submitted_at[fut] > COMPANY_HARD_TIMEOUT_SECONDS
                ]
                for fut in newly_abandoned:
                    company = futures[fut]
                    name = company["company_name"]
                    stuck_for = now - submitted_at[fut]

                    print(f"[ingestion_orchestrator] STUCK: {name} has been running for "
                          f"{stuck_for:.0f}s (limit {COMPANY_HARD_TIMEOUT_SECONDS}s) — "
                          f"abandoning it and moving on to the rest of the batch.")

                    with progress_lock:
                        completed_count[0] += 1
                        n = completed_count[0]
                        pct = 0.05 + 0.90 * (n / max(total, 1))
                        progress(pct, f"[{n}/{total}] TIMED OUT (abandoned): {name}")

                    _record_result(
                        name, [], "timeout", stuck_for,
                        f"{name}: exceeded {COMPANY_HARD_TIMEOUT_SECONDS}s hard timeout, abandoned"
                    )
                    abandoned.add(fut)

                if newly_abandoned:
                    pending = pending - abandoned
        finally:
            # wait=False: never block here on a company we already gave up
            # on above. Any abandoned task keeps running in the background;
            # see run_ingestion_db.py's __main__ for how the process still
            # exits promptly despite that.
            ex.shutdown(wait=False)
    finally:
        browser_pool.close_all()

    progress(0.97, f"Writing {len(all_jobs)} jobs to sink…")
    job_sink.write(all_jobs)
    progress(1.0, f"Done. {len(all_jobs)} jobs from {total} companies"
                  f"{f' ({timed_out_count[0]} timed out)' if timed_out_count[0] else ''}.")

    return {
        "companies_total":     total,
        "companies_ats_hit":   ats_hit_count[0],
        "companies_scraped":   scraped_count[0],
        "companies_failed":    failed_count[0],
        "companies_timed_out": timed_out_count[0],
        "jobs_found":          len(all_jobs),
        "errors":              errors,
        "per_company_timing":  timing_log,
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"