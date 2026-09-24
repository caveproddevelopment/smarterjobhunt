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

from .ats_detector import detect_ats, detect_ats_from_url
from .ats_api import fetch_jobs
from .async_career_scraper import scrape_careers_page, find_careers_url_via_playwright
from .async_browser_pool import AsyncBrowserPool
from .scraper_errors import ScraperBrowserDeadError
from .company_source import CompanySource
from .job_sink import JobSink

DEFAULT_MAX_WORKERS = 10
DEFAULT_SCRAPE_RETRIES = 2   # attempts per company against the career-scrape path
DEFAULT_BATCH_SIZE = 500     # companies processed, then written to job_sink, per sequential chunk
MAX_PROGRESS_LINES = 200     # roughly how many "[n/total] Scraped X" lines to print for the whole run
DISCOVERY_TIMEOUT_SECONDS = 35   # real-browser homepage scan for a careers link,
# including the hover+click dropdown scan in async_career_scraper.py (which
# has its own internal ~8s budget). Raised from 25 (2026-09-24) — worst case
# is now goto (20s) + the dropdown scan (~11s worst case incl. in-flight
# overrun past its own budget) ≈ 33s, so 25s risked asyncio.wait_for
# cancelling the whole discovery outright and losing a careers link the
# dropdown scan had already found.
API_RETRY_ATTEMPTS = 3           # ATS API calls, retried (with backoff) only on HTTP 429
# Hard cap on how long a single company can take. Now covers, in the worst
# case: detect_ats (~20s of plain requests) + the real-browser careers-link
# discovery (DISCOVERY_TIMEOUT_SECONDS) + a scrape of up to HARD_TIMEOUT_SECONDS
# (45s, in async_career_scraper.py) + an ATS API fetch with 429 backoff +
# browser-relaunch buffer. Raised from 100 when the discovery/fallback steps
# were added (2026-09-24).
FUTURE_TIMEOUT_SECONDS = 150


async def run(
    company_source: CompanySource,
    job_sink: JobSink,
    max_workers: int = DEFAULT_MAX_WORKERS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    progress_callback: Optional[Callable] = None,
    result_callback: Optional[Callable[[list], None]] = None,
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
        "company_results":     list[dict],   # one row per company — see below
      }

    `result_callback` (optional, diagnostics only): called once per chunk,
    right after that chunk's jobs are written, with a list of per-company
    outcome rows (`company_results`). Each row says *why* a company did or
    didn't produce jobs — see `_classify_outcome()`. Wire it to a DB table
    or CSV so a failed company is never just "0 jobs, no idea why".
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
    all_company_results: list[dict] = []
    website_by_name = {c["company_name"]: c["website"] for c in companies}
    total_jobs_written = 0

    browser_pool = AsyncBrowserPool()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async def scrape_with_retry(careers_url: str, domain: str, company_name: str,
                                scrape_diag: Optional[dict] = None) -> list[dict]:
        """Runs the Playwright fallback scrape. If the shared browser's
        driver connection has died, discards it and retries once with a
        freshly launched browser instead of leaving every other
        concurrent task sharing it silently broken too."""
        last_err = None
        for attempt in range(1, DEFAULT_SCRAPE_RETRIES + 1):
            browser = await browser_pool.get()
            try:
                return await scrape_careers_page(careers_url, domain, browser=browser,
                                                 diag=scrape_diag)
            except ScraperBrowserDeadError as e:
                last_err = e
                print(f"[async_ingestion_orchestrator] Browser died while scraping {company_name} "
                      f"(attempt {attempt}/{DEFAULT_SCRAPE_RETRIES}) — relaunching and retrying.")
                await browser_pool.invalidate()
        raise RuntimeError(f"browser kept dying while scraping {careers_url}: {last_err}")

    async def fetch_with_retry(ats: str, token: str, fetch_diag: dict) -> list[dict]:
        """ATS API fetch that backs off and retries on HTTP 429 (Workable in
        particular rate-limits) instead of giving up on the first one."""
        jobs: list[dict] = []
        attempt = 0
        for attempt in range(1, API_RETRY_ATTEMPTS + 1):
            fetch_diag.clear()
            jobs = await asyncio.to_thread(fetch_jobs, ats, token, True, fetch_diag)
            if jobs or fetch_diag.get("fetch_status") != 429:
                break
            await asyncio.sleep(2 * attempt)   # 2s, then 4s, then give up
        fetch_diag["attempts"] = attempt
        return jobs

    async def discover_careers_url(website: str, diags: dict) -> Optional[str]:
        """Real-browser homepage scan for a careers link — the fallback for
        companies where detect_ats()'s plain-`requests` probing found nothing."""
        diags["phase"] = "discover_careers"
        dd = diags["discover"]
        try:
            browser = await browser_pool.get()
            return await asyncio.wait_for(
                find_careers_url_via_playwright(website, browser=browser, diag=dd),
                timeout=DISCOVERY_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            dd["outcome"] = "timeout"
        except ScraperBrowserDeadError:
            dd["outcome"] = "browser_dead"
            await browser_pool.invalidate()
        except Exception as e:
            dd["outcome"] = f"error: {e}"[:200]
        return None

    async def scrape_or_switch_to_api(careers_url: str, name: str, diags: dict):
        """Scrapes a careers page — unless the URL is itself an ATS board, or
        the page embeds one, in which case that ATS's API is used (it's
        complete and structured; the link scraper can't see into iframes).
        Returns (jobs, source, via) where source is "ats_api" | "career_scrape"."""
        hit = detect_ats_from_url(careers_url)
        if hit:
            jobs = await fetch_with_retry(hit.ats, hit.token, diags["fetch"])
            if jobs:
                diags["ats"].update({"ats": hit.ats, "token": hit.token})
                return jobs, "ats_api", "careers_url_is_ats_board"

        diags["phase"] = "career_scrape"
        domain = _extract_domain(careers_url)
        jobs = await scrape_with_retry(careers_url, domain, name, diags["scrape"])

        emb = diags["scrape"].get("embedded_ats")
        if emb:
            api_jobs = await fetch_with_retry(emb[0], emb[1], diags["fetch"])
            if api_jobs:
                diags["ats"].update({"ats": emb[0], "token": emb[1]})
                return api_jobs, "ats_api", "embedded_ats_on_careers_page"
        return jobs, "career_scrape", None

    async def process_company(company: dict, diags: dict):
        """Process one company; returns (name, job_rows, path, elapsed, error, diags).

        `diags` is created by the caller and filled in as we go, so that if
        this coroutine gets cancelled by the FUTURE_TIMEOUT_SECONDS cap the
        caller can still see how far it got (diags["phase"])."""
        name = company["company_name"]
        website = company["website"] or None
        started = datetime.now()
        diags["phase"] = "detect_ats"

        try:
            # detect_ats() and fetch_jobs() are synchronous (requests-based)
            # calls. Run them on a worker thread rather than inline, so a
            # slow/hung DNS lookup or connection can't freeze the whole
            # event loop — see the 2026-09-10 note in the module docstring.
            ats_result = await asyncio.to_thread(detect_ats, name, website, diags["detect"])
            diags["ats"] = {
                "ats": ats_result.ats,
                "token": ats_result.token,
                "can_api": ats_result.can_api,
                "careers_url": ats_result.careers_url,
            }

            raw_jobs = []
            path_taken = "unknown"

            if ats_result.can_api and ats_result.token:
                diags["phase"] = "ats_fetch"
                raw_jobs = await fetch_with_retry(ats_result.ats, ats_result.token, diags["fetch"])
                path_taken = "ats_api"

                f = diags["fetch"]
                if not raw_jobs and f.get("fetch_error") and f.get("fetch_status") != 429:
                    # The API call failed outright (typically 404 = a wrong or stale
                    # board token). Previously the company just ended here with 0
                    # jobs. Fall back to finding + scraping its careers page — which
                    # may itself lead to the correct ATS board.
                    diags["api_failed_first"] = (
                        f"{ats_result.ats}/{ats_result.token} -> HTTP {f.get('fetch_status')}")
                    url = ats_result.careers_url
                    if not url and website:
                        url = await discover_careers_url(website, diags)
                        if url:
                            diags["ats"]["careers_url"] = url
                    if url:
                        raw_jobs, path_taken, via = await scrape_or_switch_to_api(url, name, diags)
                        diags["recovered_via"] = via or "scrape_after_api_failure"

            elif ats_result.careers_url:
                raw_jobs, path_taken, via = await scrape_or_switch_to_api(
                    ats_result.careers_url, name, diags)
                if via:
                    diags["recovered_via"] = via
                elif ats_result.ats not in ("unknown", "", None):
                    # e.g. Workday/Rippling/BambooHR: detected, now handed a URL to scrape
                    diags["recovered_via"] = f"{ats_result.ats}_careers_url"

            elif website:
                # detect_ats() found no ATS and no careers page. Look in a real browser.
                url = await discover_careers_url(website, diags)
                if url:
                    diags["ats"]["careers_url"] = url
                    raw_jobs, path_taken, via = await scrape_or_switch_to_api(url, name, diags)
                    diags["recovered_via"] = "playwright_homepage_scan" + (f"+{via}" if via else "")

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
                    "ats":            diags["ats"]["ats"],
                    "careers_url":    diags["ats"]["careers_url"] or "",
                    "source":         path_taken,
                    "scraped_at":     run_ts,
                }
                for job in raw_jobs
            ]
            return name, job_rows, path_taken, elapsed, None, diags

        except Exception as e:
            elapsed = (datetime.now() - started).total_seconds()
            return name, [], "error", elapsed, f"{name}: {e}", diags

    async def process_with_progress(company: dict):
        """Wrapper that updates progress and handles timeout."""
        name = company["company_name"]
        diags = {"phase": "not_started", "detect": {}, "fetch": {}, "scrape": {}, "discover": {}}
        try:
            result = await asyncio.wait_for(
                process_company(company, diags),
                timeout=FUTURE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            print(f"[async_ingestion_orchestrator] STUCK: {name} did not complete within "
                  f"{FUTURE_TIMEOUT_SECONDS}s — abandoning it and moving on to the rest of the batch.")
            result = (name, [], "timeout", float(FUTURE_TIMEOUT_SECONDS),
                      f"{name}: did not complete within {FUTURE_TIMEOUT_SECONDS}s", diags)
        except Exception as e:
            result = name, [], "error", 0.0, f"{name}: {e}", diags

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
            chunk_results: list[dict] = []
            for name, job_rows, path_taken, elapsed, err, diags in results:
                chunk_jobs.extend(job_rows)
                chunk_results.append(
                    _build_result_row(name, website_by_name.get(name, ""),
                                      path_taken, elapsed, len(job_rows), err, diags)
                )
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

            # Per-company outcome rows for this chunk. Diagnostics must never
            # be able to take the run down, so any failure here is logged and
            # swallowed.
            all_company_results.extend(chunk_results)
            if result_callback is not None:
                try:
                    result_callback(chunk_results)
                except Exception as e:
                    print(f"[async_ingestion_orchestrator] result_callback failed "
                          f"(diagnostics only, run continues): {e}", flush=True)

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
        "company_results":     all_company_results,
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


# ─────────────────────────────────────────────────────────────────────────────
# Per-company outcome diagnostics
# ─────────────────────────────────────────────────────────────────────────────

def _classify_outcome(path: str, jobs_found: int, err: Optional[str], d: dict) -> tuple[str, str]:
    """Returns (stage, detail) explaining this company's result.

    Stages starting with "ok_" produced jobs. Everything else is a failure
    or a zero-job result, split by *where* in the pipeline it happened:

      no_careers_url_found          neither detect_ats() nor the real-browser
                                    homepage scan found a careers page (detail
                                    says what each saw)
      ats_detected_not_scraped      (legacy) ATS detected but no URL to scrape
      ats_api_board_not_found       ATS API returned 404 (usually a wrong slug)
      ats_api_rate_limited          ATS API returned 429
      ats_api_error                 any other ATS API failure
      ats_api_empty_board           ATS API answered fine but listed 0 jobs
      scrape_hard_timeout           45s cap hit and no links had been found yet
                                    (if links HAD been found they are now kept:
                                    ok_career_scrape, "partial: hard timeout")
      scrape_page_load_timeout      page.goto() timed out
      scrape_page_error             navigation error (HTTP2 protocol error, etc.)
      scrape_page_has_no_links      page loaded, zero candidate links
      scrape_all_links_filtered_out page had links, none looked like job links
      timeout_in_<phase>            whole-company cap hit; phase = where
      exception                     unexpected exception

    For "ok_*" stages, `detail` says how the company was recovered when one of
    the fallbacks did the work (recovered_via=...): playwright_homepage_scan,
    scrape_after_api_failure, embedded_ats_on_careers_page,
    careers_url_is_ats_board, or <ats>_careers_url (Workday etc.).
    """
    detect = d.get("detect", {})
    fetch = d.get("fetch", {})
    scrape = d.get("scrape", {})
    discover = d.get("discover", {})
    ats = (d.get("ats") or {}).get("ats") or "unknown"
    rv = d.get("recovered_via")
    rv_note = f"recovered_via={rv}" if rv else ""
    after_api = f"after_api_failure=[{d['api_failed_first']}] " if d.get("api_failed_first") else ""

    if path == "timeout":
        return f"timeout_in_{d.get('phase', 'unknown')}", err or ""
    if path == "error":
        return "exception", err or ""

    if path == "ats_api":
        if jobs_found > 0:
            return "ok_ats_api", f"{ats} {rv_note}".strip()
        status = fetch.get("fetch_status")
        if status == 404:
            return "ats_api_board_not_found", f"{ats}/{(d.get('ats') or {}).get('token')}"
        if status == 429:
            return "ats_api_rate_limited", f"{ats}/{(d.get('ats') or {}).get('token')}"
        if fetch.get("fetch_error"):
            return "ats_api_error", fetch["fetch_error"]
        return "ats_api_empty_board", f"{ats}/{(d.get('ats') or {}).get('token')}"

    if path == "career_scrape":
        if jobs_found > 0:
            partial = ""
            if scrape.get("outcome") == "hard_timeout":
                partial = f" partial: hard timeout, kept {scrape.get('partial_jobs_kept')} link(s)"
            return "ok_career_scrape", f"{rv_note}{partial}".strip()
        outcome = scrape.get("outcome", "")
        if outcome == "hard_timeout":
            return "scrape_hard_timeout", after_api + f"stage={scrape.get('stage_reached')}"
        if outcome == "goto_timeout":
            return "scrape_page_load_timeout", after_api.strip()
        if outcome.startswith("error"):
            return "scrape_page_error", after_api + outcome
        if outcome == "context_error":
            return "scrape_browser_error", after_api.strip()
        if scrape.get("candidate_links", 0) == 0:
            return "scrape_page_has_no_links", after_api + (
                "page loaded but nothing matched — JS-rendered, iframe, or blocked?")
        if scrape.get("kept_links", 0) == 0:
            samples = " | ".join(scrape.get("reject_samples") or [])
            return "scrape_all_links_filtered_out", after_api + (
                f"{scrape.get('candidate_links')} candidate link(s) via "
                f"{scrape.get('listing_selector')}, 0 passed the job-link filter; "
                f"reasons={scrape.get('reject_counts')}; empty_text={scrape.get('empty_text_links')}; "
                f"samples: {samples}")
        return "scrape_zero_jobs_other", after_api.strip()

    # path == "unknown": neither the API path nor the scrape path ran.
    if ats not in ("unknown", None, ""):
        return "ats_detected_not_scraped", (
            f"{ats}: detected but no careers URL to scrape (via {detect.get('detected_via')})")
    return "no_careers_url_found", (
        f"homepage_status={detect.get('homepage_status')}; slug_tried={detect.get('slug_tried')}; "
        f"browser_discovery={discover.get('outcome', 'not_run')}")


def _build_result_row(name: str, website: str, path: str, elapsed: float,
                      jobs_found: int, err: Optional[str], d: dict) -> dict:
    stage, detail = _classify_outcome(path, jobs_found, err, d)
    a = d.get("ats") or {}
    s = d.get("scrape", {})
    return {
        "company_name":    name,
        "website":         website,
        "stage":           stage,
        "detail":          (detail or "")[:1200],
        "path":            path,
        "ats":             a.get("ats"),
        "ats_token":       a.get("token"),
        "careers_url":     a.get("careers_url"),
        "detected_via":    d.get("detect", {}).get("detected_via"),
        "homepage_status": d.get("detect", {}).get("homepage_status"),
        "jobs_found":      jobs_found,
        "elapsed_seconds": round(elapsed, 2),
        "candidate_links": s.get("candidate_links"),
        "kept_links":      s.get("kept_links"),
        "links_before_descriptions": s.get("links_before_descriptions"),
    }