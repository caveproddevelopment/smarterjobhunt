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

Fallback chain (2026-10-13, from the 7 Oct India run analysis):
  1. ATS API by name slug / homepage scan (detect_ats).
  2. Careers URL -> if it is an API board, use the API; else scrape it.
  3. While scraping: a careers page that redirects to, iframes, or links
     out to a hiring platform is followed ("platform hop"): API when we
     have an adapter, otherwise a second scrape on the platform page,
     whose jobs win if it finds any.
  4. A careers URL rejected by page validation (404/error/login/off-site,
     see platforms.classify_page) no longer ends the company: the
     real-browser homepage discovery runs and its link is tried next.
  5. net::ERR_HTTP2_PROTOCOL_ERROR -> one retry on an HTTP/1.1 browser.
Each ATS API fetch has its own API_FETCH_TIMEOUT_SECONDS cap.
"""

import asyncio
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Callable

from .ats_detector import detect_ats, detect_ats_from_url
from .ats_api import fetch_jobs
from .async_career_scraper import scrape_careers_page, find_careers_url_via_playwright
from .platforms import platform_for_url, parse_ats_url, API_ATS, host_of
from .async_browser_pool import AsyncBrowserPool
from .scraper_errors import ScraperBrowserDeadError
from .company_source import CompanySource
from .job_sink import JobSink

# ─────────────────────────────────────────────────────────────────────────────
# Detailed per-company logging (2026-10-14)
#
# Every company now prints one block when it finishes:
#   [  37/603] OK       Acko | 23 jobs | ok_ats_api | greenhouse | 4.1s
#              +  0.0s start website=https://acko.com careers_url_override=none
#              +  2.3s detect_ats -> ats=greenhouse token=acko api=True ...
#              +  3.9s api greenhouse/acko -> 23 job(s) status=200 error=none attempts=1
# FAILED/TIMEOUT blocks carry the stage + reason and the same step trace, so
# no company is ever "unknown". The trace is also saved to
# scrape_company_results.trace.
# ─────────────────────────────────────────────────────────────────────────────

NO_ATS = "none_detected"          # shown instead of the detector's internal "unknown"
NO_PATH = "no_scrape_path"        # neither the API nor a careers-page scrape ran


def _disp_ats(ats) -> str:
    return NO_ATS if ats in (None, "", "unknown") else str(ats)


def _trace(diags: dict, msg: str) -> None:
    """Append one timestamped step to this company's trace."""
    t0 = diags.setdefault("_t0", time.monotonic())
    msg = " | ".join(part.strip() for part in str(msg).splitlines() if part.strip())
    diags.setdefault("trace", []).append(f"+{time.monotonic() - t0:6.1f}s {msg[:1500]}")


def _scrape_summary(sd: dict, n: int) -> str:
    """One-line description of a careers-page scrape from its diag dict."""
    parts = [f"outcome={sd.get('outcome') or 'ok'}", f"kept_jobs={n}"]
    for key, label in (("final_url", "final_url"), ("page_invalid", "rejected_as"),
                       ("candidate_links", "candidate_links"), ("kept_links", "kept_links"),
                       ("listing_selector", "selector"), ("json_responses", "json_responses"),
                       ("stage_reached", "stage_reached"), ("partial_jobs_kept", "partial_kept"),
                       ("browser_restarts", "browser_restarts")):
        v = sd.get(key)
        if v not in (None, "", [], {}):
            parts.append(f"{label}={str(v)[:120]}")
    if sd.get("used_json_capture"):
        parts.append("via_json_capture")
    if sd.get("retried_http1"):
        parts.append("retried_on_http1")
    if sd.get("embedded_ats"):
        parts.append(f"embedded_ats={sd['embedded_ats']}")
    if sd.get("platform_urls"):
        parts.append(f"platform_urls={[u[:80] for u in sd['platform_urls'][:3]]}")
    if sd.get("reject_counts"):
        parts.append(f"filter_rejects={sd['reject_counts']}")
    return " ".join(parts)


def _fetch_summary(fd: dict, n: int) -> str:
    return (f"{fd.get('ats', '?')} -> {n} job(s) status={fd.get('fetch_status') or '-'} "
            f"error={fd.get('fetch_error') or 'none'} attempts={fd.get('attempts', 1)}")


DEFAULT_MAX_WORKERS = 10
DEFAULT_SCRAPE_RETRIES = 2   # attempts per company against the career-scrape path
DEFAULT_BATCH_SIZE = 500     # companies processed, then written to job_sink, per sequential chunk
MAX_PROGRESS_LINES = 200     # unused since 2026-10-14: every company now prints its own block
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
FUTURE_TIMEOUT_SECONDS = 210   # raised from 150 (2026-10-13): platform hop, HTTP/1.1
                               # retry and sitemap lookup each add a bounded step
API_FETCH_TIMEOUT_SECONDS = 60  # own cap for one ATS API fetch (incl. detail calls)


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
    progress(0.02, f"Loaded {total} companies.")

    all_errors: list[str] = []
    all_timing_log: list[dict] = []
    all_company_results: list[dict] = []
    website_by_name = {c["company_name"]: c["website"] for c in companies}
    total_jobs_written = 0

    browser_pool = AsyncBrowserPool()
    run_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")

    async def scrape_with_retry(careers_url: str, domain: str, company_name: str,
                                scrape_diag: Optional[dict] = None,
                                company_host: str = "") -> list[dict]:
        """Runs the Playwright scrape. Dead browser -> relaunch and retry.
        HTTP/2 protocol error -> one retry on the HTTP/1.1 browser."""
        if scrape_diag is None:
            scrape_diag = {}
        last_err = None
        http1 = False
        attempt = 0
        while attempt < DEFAULT_SCRAPE_RETRIES + 1:
            attempt += 1
            browser = await browser_pool.get(http1=http1)
            try:
                jobs = await scrape_careers_page(careers_url, domain, browser=browser,
                                                 diag=scrape_diag, company_host=company_host)
            except ScraperBrowserDeadError as e:
                last_err = e
                scrape_diag["browser_restarts"] = scrape_diag.get("browser_restarts", 0) + 1
                print(f"[async_ingestion_orchestrator] Browser died while scraping {company_name} "
                      f"(attempt {attempt}): {type(e).__name__}: {e} — relaunching and retrying.",
                      flush=True)
                await browser_pool.invalidate()
                if attempt >= DEFAULT_SCRAPE_RETRIES:
                    break
                continue
            if scrape_diag.get("outcome") == "http2_error" and not http1:
                scrape_diag.clear()
                scrape_diag["retried_http1"] = True
                http1 = True
                continue
            return jobs
        raise RuntimeError(f"browser kept dying while scraping {careers_url}: {last_err}")

    async def fetch_with_retry(ats: str, token: str, fetch_diag: dict) -> list[dict]:
        """ATS API fetch that backs off and retries on HTTP 429, with its own
        overall cap so a slow API can't eat the whole company budget."""
        jobs: list[dict] = []
        attempt = 0
        for attempt in range(1, API_RETRY_ATTEMPTS + 1):
            fetch_diag.clear()
            try:
                jobs = await asyncio.wait_for(
                    asyncio.to_thread(fetch_jobs, ats, token, True, fetch_diag),
                    timeout=API_FETCH_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                fetch_diag["fetch_error"] = f"api fetch exceeded {API_FETCH_TIMEOUT_SECONDS}s"
                jobs = []
                break
            if jobs or fetch_diag.get("fetch_status") != 429:
                break
            await asyncio.sleep(2 * attempt)   # 2s, then 4s, then give up
        fetch_diag["attempts"] = attempt
        fetch_diag["ats"] = f"{ats}/{token}"
        return jobs

    async def discover_careers_url(website: str, diags: dict) -> Optional[str]:
        """Real-browser homepage scan for a careers link — the fallback for
        companies where detect_ats()'s plain-`requests` probing found nothing
        usable. Retries once on the HTTP/1.1 browser after an HTTP/2 error."""
        if diags.get("discovery_ran"):
            return None
        diags["discovery_ran"] = True
        diags["phase"] = "discover_careers"
        dd = diags["discover"]
        for http1 in (False, True):
            try:
                browser = await browser_pool.get(http1=http1)
                url = await asyncio.wait_for(
                    find_careers_url_via_playwright(website, browser=browser, diag=dd),
                    timeout=DISCOVERY_TIMEOUT_SECONDS,
                )
                if dd.get("outcome") == "http2_error" and not http1:
                    _trace(diags, f"homepage discovery {website} -> http2_error, retrying on HTTP/1.1")
                    dd.clear()
                    dd["retried_http1"] = True
                    continue
                _trace(diags, f"homepage discovery {website} -> outcome={dd.get('outcome') or 'ok'} "
                              f"careers_link={url or 'none'}")
                return url
            except asyncio.TimeoutError:
                dd["outcome"] = f"timeout (>{DISCOVERY_TIMEOUT_SECONDS}s)"
            except ScraperBrowserDeadError as e:
                dd["outcome"] = f"browser_dead: {e}"[:200]
                await browser_pool.invalidate()
            except Exception as e:
                dd["outcome"] = f"error: {type(e).__name__}: {e}"[:200]
            _trace(diags, f"homepage discovery {website} -> FAILED {dd.get('outcome')}")
            return None
        return None

    def _note_attempt(diags: dict, url: str, sd: dict, n: int):
        diags.setdefault("attempts", []).append(
            f"{url[:90]} -> {sd.get('outcome') or 'ok'}"
            + (f"/{sd['page_invalid']}" if sd.get("page_invalid") else "")
            + f" kept={n}" + (" json" if sd.get("used_json_capture") else ""))

    async def try_api(ats: str, token: str, diags: dict) -> list[dict]:
        jobs = await fetch_with_retry(ats, token, diags["fetch"])
        _trace(diags, "api " + _fetch_summary(diags["fetch"], len(jobs)))
        if jobs:
            diags["ats"].update({"ats": ats, "token": token})
        return jobs

    async def scrape_or_switch_to_api(careers_url: str, name: str, diags: dict,
                                      company_host: str = ""):
        """Gets jobs for one careers URL. Returns (jobs, source, via) where
        source is "ats_api" | "career_scrape". Order: the URL is itself an
        API board -> API; scrape it; the page embeds an API board -> API;
        the page hands off to another hiring-platform host -> follow it."""
        hit = detect_ats_from_url(careers_url)
        if hit:
            _trace(diags, f"careers URL is a {hit.ats} board (token={hit.token}) -> calling its API")
            jobs = await try_api(hit.ats, hit.token, diags)
            if jobs:
                return jobs, "ats_api", "careers_url_is_ats_board"

        diags["phase"] = "career_scrape"
        sd: dict = {}
        jobs = await scrape_with_retry(careers_url, _extract_domain(careers_url), name, sd,
                                       company_host=company_host)
        diags["scrape"] = sd
        _note_attempt(diags, careers_url, sd, len(jobs))
        _trace(diags, f"scrape {careers_url} -> " + _scrape_summary(sd, len(jobs)))

        emb = sd.get("embedded_ats")
        if emb:
            _trace(diags, f"careers page embeds {emb[0]} board (token={emb[1]}) -> calling its API")
            api_jobs = await try_api(emb[0], emb[1], diags)
            if api_jobs:
                return api_jobs, "ats_api", "embedded_ats_on_careers_page"

        # Platform hop: careers page -> Darwinbox/Keka/PeopleStrong/... page.
        scraped_host = host_of(sd.get("final_url") or careers_url)
        on_platform = platform_for_url(sd.get("final_url") or careers_url) is not None
        for purl in sd.get("platform_urls", [])[:2]:
            if host_of(purl) == scraped_host:
                continue
            if jobs and on_platform:
                break
            plat = platform_for_url(purl) or "platform"
            h = parse_ats_url(purl)
            if h and h[0] in API_ATS:
                api_jobs = await try_api(h[0], h[1], diags)
                if api_jobs:
                    return api_jobs, "ats_api", f"platform_hop_api:{h[0]}"
                continue
            diags["phase"] = "platform_hop"
            _trace(diags, f"platform hop -> {plat}: {purl}")
            hd: dict = {}
            hop_jobs = await scrape_with_retry(purl, _extract_domain(purl), name, hd,
                                               company_host=company_host)
            _note_attempt(diags, purl, hd, len(hop_jobs))
            _trace(diags, f"scrape {purl} -> " + _scrape_summary(hd, len(hop_jobs)))
            if hop_jobs:
                diags["scrape"] = hd
                diags["ats"].update({"ats": plat, "careers_url": purl})
                return hop_jobs, "career_scrape", f"platform_hop:{plat}"
            if not jobs:
                diags["scrape"] = hd if hd.get("outcome") not in (None, "ok") else sd
        return jobs, "career_scrape", None

    async def process_company(company: dict, diags: dict):
        """Process one company; returns (name, job_rows, path, elapsed, error, diags).

        `diags` is created by the caller and filled in as we go, so that if
        this coroutine gets cancelled by the FUTURE_TIMEOUT_SECONDS cap the
        caller can still see how far it got (diags["phase"])."""
        name = company["company_name"]
        website = company["website"] or None
        company_host = host_of(website) if website else ""
        started = datetime.now()
        diags["phase"] = "detect_ats"

        try:
            diags["ats"] = {"ats": "unknown", "token": None, "can_api": False, "careers_url": None}

            raw_jobs: list[dict] = []
            path_taken = NO_PATH
            tried_urls: set = set()

            async def via_url(url: str):
                """Scrape/API one careers URL; returns (jobs, path, via)."""
                tried_urls.add(url.split("#")[0].rstrip("/"))
                _trace(diags, f"trying careers URL {url}")
                return await scrape_or_switch_to_api(url, name, diags, company_host=company_host)

            async def via_discovery():
                if not website:
                    return [], None, None
                url = await discover_careers_url(website, diags)
                if not url or url.split("#")[0].rstrip("/") in tried_urls:
                    return [], None, None
                diags["ats"]["careers_url"] = url
                j, p, v = await via_url(url)
                return j, p, "playwright_homepage_scan" + (f"+{v}" if v else "")

            override = (company.get("careers_url") or "").strip()
            _trace(diags, f"start website={website or 'NONE (no website stored)'} "
                          f"careers_url_override={override or 'none'}")
            if override:
                if not override.startswith("http"):
                    override = "https://" + override
                # A careers URL set by hand in companies.careers_url wins over
                # anything detected; detection only runs again if it yields nothing.
                diags["careers_url_override"] = override
                j, p, v = await via_url(override)
                _trace(diags, f"override result -> {len(j)} job(s) via {p}" + (f" ({v})" if v else ""))
                if j:
                    raw_jobs, path_taken = j, p
                    diags["ats"]["careers_url"] = override
                    diags["recovered_via"] = "careers_url_override" + (f"+{v}" if v else "")

            if not raw_jobs:
                diags["phase"] = "detect_ats"
                ats_result = await asyncio.to_thread(detect_ats, name, website, diags["detect"])
                diags["ats"] = {
                    "ats": ats_result.ats,
                    "token": ats_result.token,
                    "can_api": ats_result.can_api,
                    "careers_url": ats_result.careers_url,
                }
                dt = diags["detect"]
                extra = ""
                if dt.get("rejected_guesses"):
                    extra += f" rejected_guesses={dt['rejected_guesses'][:4]}"
                if dt.get("sitemap"):
                    extra += f" sitemap={dt['sitemap']}"
                if dt.get("catch_all_site"):
                    extra += " catch_all_site"
                _trace(diags, f"detect_ats -> ats={_disp_ats(ats_result.ats)} "
                              f"token={ats_result.token or '-'} api={ats_result.can_api} "
                              f"careers_url={ats_result.careers_url or 'none'} "
                              f"via={dt.get('detected_via') or '-'} "
                              f"homepage_status={dt.get('homepage_status') or '-'} "
                              f"slug_tried={dt.get('slug_tried') or '-'}{extra}")
            else:
                ats_result = None

            if ats_result is None:
                pass
            elif ats_result.can_api and ats_result.token:
                diags["phase"] = "ats_fetch"
                raw_jobs = await fetch_with_retry(ats_result.ats, ats_result.token, diags["fetch"])
                _trace(diags, "api " + _fetch_summary(diags["fetch"], len(raw_jobs)))
                path_taken = "ats_api"

                f = diags["fetch"]
                if not raw_jobs and f.get("fetch_status") != 429:
                    # Errored OR clean-but-empty board (stale token, abandoned
                    # board): fall back to the careers page / homepage discovery.
                    diags["api_empty_or_failed"] = (
                        f"{ats_result.ats}/{ats_result.token} -> "
                        + (f"HTTP {f.get('fetch_status')}" if f.get("fetch_error")
                           else "empty board (0 jobs, no error)")
                    )
                    url = ats_result.careers_url
                    if url and detect_ats_from_url(url):
                        url = None   # the careers URL *is* the board we just asked
                    if url:
                        raw_jobs, path_taken, via = await via_url(url)
                        diags["recovered_via"] = via or "scrape_after_empty_or_failed_api"
                    if not raw_jobs:
                        j, p, v = await via_discovery()
                        if j:
                            raw_jobs, path_taken = j, p
                            diags["recovered_via"] = v
                        elif p and path_taken == "ats_api" and not url:
                            path_taken = p

            elif ats_result.careers_url and (
                    ats_result.careers_url.split("#")[0].rstrip("/") not in tried_urls):
                raw_jobs, path_taken, via = await via_url(ats_result.careers_url)
                if via:
                    diags["recovered_via"] = via
                elif ats_result.ats not in ("unknown", "", None):
                    diags["recovered_via"] = f"{ats_result.ats}_careers_url"
                if not raw_jobs:
                    # The guessed/scanned careers URL was wrong (error page,
                    # login, off-site ...) or empty: let the real-browser
                    # homepage scan find the link a human would click.
                    j, p, v = await via_discovery()
                    if j:
                        raw_jobs, path_taken = j, p
                        diags["recovered_via"] = v

            elif website:
                _trace(diags, "no API board and no careers URL from detect_ats -> homepage discovery")
                j, p, v = await via_discovery()
                if p:
                    raw_jobs, path_taken = j, p
                    diags["recovered_via"] = v
            else:
                _trace(diags, "no website stored and no careers_url override -> nothing to scrape")

            elapsed = (datetime.now() - started).total_seconds()

            dropped = sum(1 for job in raw_jobs
                          if not ((job.get("title") or "").strip() and (job.get("apply_url") or "").strip()))
            if dropped:
                _trace(diags, f"dropped {dropped} of {len(raw_jobs)} raw job(s) missing title or apply_url")
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
                if (job.get("title") or "").strip() and (job.get("apply_url") or "").strip()
            ]
            return name, job_rows, path_taken, elapsed, None, diags

        except Exception as e:
            elapsed = (datetime.now() - started).total_seconds()
            diags["traceback"] = traceback.format_exc()
            _trace(diags, f"EXCEPTION in phase={diags.get('phase')}: {type(e).__name__}: {e}")
            return name, [], "error", elapsed, f"{name}: {type(e).__name__}: {e}", diags

    async def process_with_progress(company: dict):
        """Wrapper that updates progress and handles timeout."""
        name = company["company_name"]
        diags = {"phase": "not_started", "detect": {}, "fetch": {}, "scrape": {}, "discover": {},
                 "_t0": time.monotonic()}
        try:
            result = await asyncio.wait_for(
                process_company(company, diags),
                timeout=FUTURE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            _trace(diags, f"ABANDONED: company cap of {FUTURE_TIMEOUT_SECONDS}s hit while in "
                          f"phase={diags.get('phase')}")
            result = (name, [], "timeout", float(FUTURE_TIMEOUT_SECONDS),
                      f"{name}: did not complete within {FUTURE_TIMEOUT_SECONDS}s "
                      f"(stuck in phase={diags.get('phase')})", diags)
        except Exception as e:
            diags["traceback"] = traceback.format_exc()
            _trace(diags, f"EXCEPTION (outer): {type(e).__name__}: {e}")
            result = name, [], "error", 0.0, f"{name}: {type(e).__name__}: {e}", diags

        state["completed_count"] += 1
        n = state["completed_count"]
        pct = 0.05 + 0.90 * (n / max(total, 1))
        rname, job_rows, path_taken, elapsed, err, d = result
        try:
            row = _build_result_row(rname, website_by_name.get(rname, ""), path_taken,
                                    elapsed, len(job_rows), err, d)
        except Exception as e:   # diagnostics must never take the run down
            row = {"company_name": rname, "website": website_by_name.get(rname, ""),
                   "stage": "diagnostics_error", "path": path_taken, "jobs_found": len(job_rows),
                   "elapsed_seconds": round(elapsed, 2),
                   "detail": f"building the result row failed: {type(e).__name__}: {e}",
                   "trace": "\n".join(d.get("trace", []))}
        _print_company_block(n, total, pct, row, d)
        return result + (row,)

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
            for name, job_rows, path_taken, elapsed, err, diags, row in results:
                chunk_jobs.extend(job_rows)
                chunk_results.append(row)
                all_timing_log.append({
                    "company_name": name,
                    "path": path_taken,
                    "elapsed_seconds": round(elapsed, 2),
                    "jobs_found": len(job_rows),
                })

                # Counted by outcome, not by path: a company whose ATS API
                # answered with 0 jobs is a failure, not an "ATS API hit".
                stage = row.get("stage", "")
                if stage == "ok_ats_api":
                    state["ats_hit_count"] += 1
                elif stage == "ok_career_scrape":
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


def _print_company_block(n: int, total: int, pct: float, row: dict, d: dict) -> None:
    """Prints one company's result + step trace as a single write, so blocks
    from concurrent companies never interleave in the log."""
    stage = row.get("stage") or "no_stage_recorded"
    jobs = row.get("jobs_found") or 0
    if stage.startswith("ok_"):
        status = "OK"
    elif stage.startswith("timeout_"):
        status = "TIMEOUT"
    elif stage == "exception":
        status = "ERROR"
    else:
        status = "FAILED"
    width = len(str(total))
    head = (f"[{int(pct * 100):3d}%] [{n:>{width}}/{total}] {status:<7} {row.get('company_name')} | "
            f"{jobs} job(s) | {stage} | {(row.get('detail') or '-')[:600]} | "
            f"{row.get('elapsed_seconds', 0)}s")
    pad = " " * 14
    lines = [head]
    lines += [pad + step for step in (d.get("trace") or [])]
    if d.get("traceback"):
        lines += [pad + "TRACEBACK: " + l for l in d["traceback"].rstrip().splitlines()]
    print("\n".join(lines), flush=True)


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

      website_unreachable           DNS/connection failure on the stored website
      website_ssl_error             TLS/certificate failure on the stored website
      website_parked                stored website is parked / for sale / placeholder
      blocked_bot_wall              Cloudflare / perfdrive / "Access Denied" wall
      no_careers_url_found          neither detect_ats() nor the real-browser
                                    homepage scan found a careers page
      ats_detected_not_scraped      (legacy) ATS detected but no URL to scrape
      ats_api_board_not_found       ATS API returned 404 (usually a wrong slug)
      ats_api_rate_limited          ATS API returned 429
      ats_api_error                 any other ATS API failure
      ats_api_empty_board           ATS API answered fine but listed 0 jobs
      scrape_invalid_page           every careers URL tried was rejected by
                                    page validation (detail: reason, e.g.
                                    not_found_page, login_page, off_site_redirect)
      scrape_http2_error            HTTP/2 protocol error even after HTTP/1.1 retry
      scrape_hard_timeout           hard cap hit and no links had been found yet
      scrape_page_load_timeout      page.goto() timed out
      scrape_page_error             navigation error
      scrape_page_has_no_links      page loaded, zero candidate links, no job JSON
      scrape_all_links_filtered_out page had links, none looked like job links
      timeout_in_<phase>            whole-company cap hit; phase = where
      exception                     unexpected exception

    `detail` always ends with attempts=[url -> outcome kept=N, ...] when
    more than one URL was tried, so a failure can be traced end to end.
    """
    detect = d.get("detect", {})
    fetch = d.get("fetch", {})
    scrape = d.get("scrape", {})
    discover = d.get("discover", {})
    ats = _disp_ats((d.get("ats") or {}).get("ats"))
    rv = d.get("recovered_via")
    rv_note = f"recovered_via={rv}" if rv else ""
    after_api = f"after_api_empty_or_failed=[{d['api_empty_or_failed']}] " if d.get("api_empty_or_failed") else ""
    attempts = d.get("attempts") or []
    # Every URL tried is listed when there was more than one, and always when
    # the company ended with 0 jobs, so a failed override is never hidden.
    att_note = (" attempts=[" + " | ".join(attempts[:5]) + "]") if (
        len(attempts) > 1 or (attempts and jobs_found == 0)) else ""

    def finish(stage, detail):
        return stage, (detail + att_note).strip()

    if path == "timeout":
        return finish(f"timeout_in_{d.get('phase') or 'not_started'}",
                      (err or "") + f" last_steps={(d.get('trace') or [])[-3:]}")
    if path == "error":
        tb = [l.strip() for l in (d.get("traceback") or "").strip().splitlines()
              if l.strip() and set(l.strip()) != {"^"} and set(l.strip()) != {"^", "~"}]
        files = [i for i, l in enumerate(tb) if l.startswith("File ")]
        where = (tb[files[-1]] + (" -> " + tb[files[-1] + 1] if files[-1] + 1 < len(tb) - 1 else "")
                 if files else "")
        return finish("exception", f"{err or 'exception with no message'} at: {where}".strip())

    if path == "ats_api":
        if jobs_found > 0:
            return finish("ok_ats_api", f"{ats} {rv_note}".strip())
        status = fetch.get("fetch_status")
        tok = f"{ats}/{(d.get('ats') or {}).get('token')}"
        if status == 404:
            return finish("ats_api_board_not_found", tok)
        if status == 429:
            return finish("ats_api_rate_limited", tok)
        if fetch.get("fetch_error"):
            return finish("ats_api_error", fetch["fetch_error"])
        return finish("ats_api_empty_board", tok)

    if path == "career_scrape":
        if jobs_found > 0:
            partial = ""
            if scrape.get("outcome") == "hard_timeout":
                partial = f" partial: hard timeout, kept {scrape.get('partial_jobs_kept')} link(s)"
            json_note = " via_json_capture" if scrape.get("used_json_capture") else ""
            return finish("ok_career_scrape", f"{rv_note}{partial}{json_note}".strip())
        outcome = scrape.get("outcome", "")
        if outcome == "invalid_page":
            reason = scrape.get("page_invalid", "")
            if reason == "bot_wall":
                return finish("blocked_bot_wall", after_api + f"final_url={scrape.get('final_url')}")
            if reason == "parked_domain":
                return finish("website_parked", after_api + f"final_url={scrape.get('final_url')}")
            return finish("scrape_invalid_page", after_api + f"reason={reason} final_url={scrape.get('final_url')}")
        if outcome == "http2_error":
            return finish("scrape_http2_error", after_api.strip())
        if outcome == "hard_timeout":
            return finish("scrape_hard_timeout", after_api + f"stage={scrape.get('stage_reached')}")
        if outcome == "goto_timeout":
            return finish("scrape_page_load_timeout", after_api.strip())
        if outcome.startswith("error: site_unreachable"):
            return finish("website_unreachable", after_api + outcome)
        if outcome.startswith("error: ssl"):
            return finish("website_ssl_error", after_api + outcome)
        if outcome.startswith("error"):
            return finish("scrape_page_error", after_api + outcome)
        if outcome == "context_error":
            return finish("scrape_browser_error", after_api.strip())
        if scrape.get("candidate_links", 0) == 0:
            return finish("scrape_page_has_no_links", after_api + (
                f"page loaded but no links; json_responses={scrape.get('json_responses', 0)} "
                f"platform_urls={scrape.get('platform_urls', [])[:2]}"))
        if scrape.get("kept_links", 0) == 0:
            samples = " | ".join(scrape.get("reject_samples") or [])
            return finish("scrape_all_links_filtered_out", after_api + (
                f"{scrape.get('candidate_links')} candidate link(s) via "
                f"{scrape.get('listing_selector')}, 0 passed the job-link filter; "
                f"reasons={scrape.get('reject_counts')}; json_responses={scrape.get('json_responses', 0)}; "
                f"samples: {samples}"))
        return finish("scrape_zero_jobs_other", after_api + _scrape_summary(scrape, 0))

    # path == NO_PATH: neither the API path nor the scrape path ran.
    hs = str(detect.get("homepage_status") or "")
    dout = str(discover.get("outcome") or "")
    if "bot_wall" in dout:
        return finish("blocked_bot_wall", f"homepage_status={hs}; browser_discovery={dout}")
    if "parked_domain" in dout:
        return finish("website_parked", f"homepage_status={hs}; browser_discovery={dout}")
    if hs.startswith("error: SSLError") or "ERR_CERT" in dout or "ERR_SSL" in dout:
        return finish("website_ssl_error", f"homepage_status={hs}; browser_discovery={dout}")
    if (hs.startswith("error: ConnectionError") or hs.startswith("error: ConnectTimeout")
            or hs.startswith("error: ProxyError")) and (
            "ERR_NAME_NOT_RESOLVED" in dout or "ERR_CONNECTION" in dout or "ERR_ADDRESS" in dout
            or "ERR_TUNNEL" in dout or dout.startswith("timeout") or dout == ""):
        return finish("website_unreachable", f"homepage_status={hs}; browser_discovery={dout}")
    if ats != NO_ATS:
        return finish("ats_detected_not_scraped", (
            f"{ats}: detected but no careers URL to scrape (via {detect.get('detected_via')})"))
    extra = ""
    if detect.get("rejected_guesses"):
        extra += f"; rejected_guesses={detect['rejected_guesses'][:4]}"
    if detect.get("sitemap"):
        extra += f"; sitemap={detect['sitemap']}"
    if detect.get("catch_all_site"):
        extra += "; catch_all_site"
    return finish("no_careers_url_found", (
        f"homepage_status={hs}; slug_tried={detect.get('slug_tried')}; "
        f"browser_discovery={dout or 'not_run'}{extra}"))


def _build_result_row(name: str, website: str, path: str, elapsed: float,
                      jobs_found: int, err: Optional[str], d: dict) -> dict:
    stage, detail = _classify_outcome(path, jobs_found, err, d)
    detail = " | ".join(p.strip() for p in str(detail or "").splitlines() if p.strip())
    if not (detail or "").strip():
        detail = ("no further detail recorded; last steps: "
                  + " / ".join((d.get("trace") or ["(no steps recorded)"])[-3:]))
    a = d.get("ats") or {}
    s = d.get("scrape", {})
    trace = list(d.get("trace") or [])
    if d.get("traceback"):
        trace.append("TRACEBACK:\n" + d["traceback"].rstrip())
    return {
        "company_name":    name,
        "website":         website,
        "stage":           stage,
        "detail":          (detail or "")[:2000],
        "trace":           "\n".join(trace)[:20000],
        "path":            path,
        "ats":             _disp_ats(a.get("ats")),
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