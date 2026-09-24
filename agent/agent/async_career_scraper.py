"""
Async Career Scraper — Playwright async API for fallback job scraping.

This replaces the sync API with native async/await, eliminating greenlet
context-switching issues and improving concurrency.

Returns the same normalized dict shape as ats_api.py:
  { title, department, location, apply_url, posted_at }

Reliability fixes (2026-08-24, after a driver crash on the sync
pipeline — see career_scraper.py's module docstring for the full
incident writeup):
  - `ctx.new_page()` used to sit outside the try/finally that closes
    the context, so a failure there leaked the context. It's now
    inside, and a browser-dead error (the driver connection itself
    dying, not an ordinary per-page failure) is raised as
    `ScraperBrowserDeadError` so `async_ingestion_orchestrator.py` can
    discard the shared browser and retry with a fresh one, instead of
    the error being logged and swallowed while every subsequent task
    sharing the same dead browser silently fails too.
  - The old Python-3.11-vs-fallback branches duplicated the whole
    scrape body with slightly different timeout coverage: the 3.11+
    branch's `asyncio.timeout()` wrapped the entire scrape (page open,
    navigation, link extraction), but the pre-3.11 fallback's
    `asyncio.wait_for()` only wrapped the `page.goto()` call, leaving
    the link-extraction loop with no hard cap on that Python version.
    Both branches now call the same `_scrape_in_context()` helper, so
    the hard timeout covers the same work either way and any future
    fix only needs to happen once.
"""

import asyncio
import re
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

from .ats_detector import _extract_ats_from_html
from .scraper_errors import ScraperBrowserDeadError, is_dead_browser_error
from .text_extract import DESCRIPTION_SNIPPET_CHARS, make_snippet

# Hard wall-clock cap on top of Playwright's own per-call timeouts.
HARD_TIMEOUT_SECONDS = 45

# Job-description fetching (one extra page load per job link) used to run
# sequentially inside the hard timeout above, and a timeout threw away every
# link already found. Now: links are kept if the cap fires, descriptions are
# fetched a few at a time, only for the first MAX_DESCRIPTION_FETCHES jobs, and
# no new fetch starts after DESCRIPTION_BUDGET_SECONDS. Each in-flight fetch is a
# Chromium page and up to 10 companies run at once, so keep DESCRIPTION_CONCURRENCY
# small — the pipeline has crashed from browser memory pressure before.
MAX_DESCRIPTION_FETCHES = 60
DESCRIPTION_CONCURRENCY = 3
DESCRIPTION_BUDGET_SECONDS = 22

LISTING_SELECTORS = [
    "a[href*='/job']",
    "a[href*='/jobs/']",
    "a[href*='/careers/']",
    "a[href*='/position']",
    "a[href*='/opening']",
    "a[href*='/apply']",
    ".job-listing a",
    ".job-title a",
    ".careers-listing a",
    ".open-position a",
    "[data-job-id]",
    "[data-automation='job-title']",
    "li.job a",
    "div.job a",
    "article.job a",
]

CAREER_PATHS = [
    "/careers", "/jobs", "/about/careers", "/company/careers",
    "/company/jobs", "/about/jobs", "/join-us", "/work-with-us",
    "/open-positions", "/opportunities", "/team/careers",
]


async def scrape_careers_page(careers_url: str, base_domain: str, browser=None,
                              diag: Optional[dict] = None) -> list[dict]:
    """
    Navigate to a careers page and extract job links (async version).

    `browser`: an already-launched playwright async Chromium browser.
    If None, launches one for this call only.

    Raises `ScraperBrowserDeadError` if the browser's driver connection
    has died. Callers using a shared/pooled browser should catch this
    specifically, discard the browser, and retry with a fresh one
    rather than treating it as an ordinary per-company failure.
    """
    if browser is not None:
        return await _scrape_with_browser(browser, careers_url, base_domain, diag=diag)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[async_career_scraper] Playwright not installed; skipping scrape.")
        return []

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        try:
            return await _scrape_with_browser(b, careers_url, base_domain, diag=diag)
        finally:
            await b.close()


async def _extract_links(page, careers_url: str, base_domain: str,
                         diag: Optional[dict] = None) -> list[dict]:
    """Shared link-extraction logic."""
    jobs = []
    links = []
    matched_selector = None
    for sel in LISTING_SELECTORS:
        try:
            els = await page.query_selector_all(sel)
            if els:
                links = els
                matched_selector = sel
                break
        except Exception:
            continue

    if not links:
        links = await page.query_selector_all("a[href]")
        matched_selector = "a[href] (fallback)"

    if diag is not None:
        # Diagnostics only: how many candidate links the page offered vs.
        # how many survived _looks_like_job_link() below.
        diag["listing_selector"] = matched_selector
        diag["candidate_links"] = len(links)

    seen_hrefs = set()
    # Diagnostics only: why candidate links were rejected (see _job_link_reject_reason).
    reject_counts: dict[str, int] = {}
    reject_samples: list[str] = []
    empty_text = 0
    for el in links:
        try:
            href = await el.get_attribute("href") or ""
            text = (await el.inner_text() or "").strip()

            if not text or not href:
                if href and not text:
                    empty_text += 1   # e.g. image/logo-only anchors
                continue

            if href.startswith("/"):
                href = base_domain.rstrip("/") + href
            elif not href.startswith("http"):
                href = urljoin(careers_url, href)

            reason = _job_link_reject_reason(href, text)
            if reason:
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
                if len(reject_samples) < 6:
                    one_line = re.sub(r"\s+", " ", text)[:50]
                    reject_samples.append(f"[{reason}] {one_line!r} -> {href[:80]}")
                continue

            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            jobs.append({
                "title":      _clean_title(text),
                "department": "",
                "location":   "",
                "apply_url":  href,
                "posted_at":  "",
                "description_snippet": "",
            })
        except Exception:
            continue

    if diag is not None:
        diag["kept_links"] = len(jobs)
        diag["reject_counts"] = reject_counts
        diag["reject_samples"] = reject_samples
        diag["empty_text_links"] = empty_text
    return jobs


async def _fetch_job_description_snippet(ctx, url: str) -> str:
    """Load one job page and return its cleaned description snippet."""
    from playwright.async_api import TimeoutError as PWTimeout

    try:
        page = await ctx.new_page()
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return ""

    try:
        await page.goto(url, timeout=15_000, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)
        html = await page.content()
        return make_snippet(html, is_html=True, max_chars=DESCRIPTION_SNIPPET_CHARS)
    except PWTimeout:
        return ""
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return ""
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def _fill_descriptions(ctx, jobs: list[dict]) -> None:
    """Fetch description snippets for (up to MAX_DESCRIPTION_FETCHES of) `jobs`,
    DESCRIPTION_CONCURRENCY at a time, mutating each job dict in place. Never
    starts a new fetch after DESCRIPTION_BUDGET_SECONDS. Because the dicts are
    mutated in place, a hard timeout that cancels this still leaves every job
    that already got a description intact."""
    todo = [j for j in jobs if j.get("apply_url")][:MAX_DESCRIPTION_FETCHES]
    if not todo:
        return
    sem = asyncio.Semaphore(DESCRIPTION_CONCURRENCY)
    deadline = time.monotonic() + DESCRIPTION_BUDGET_SECONDS

    async def one(job: dict):
        async with sem:
            if time.monotonic() >= deadline:
                return
            job["description_snippet"] = await _fetch_job_description_snippet(ctx, job["apply_url"])

    results = await asyncio.gather(*(one(j) for j in todo), return_exceptions=True)
    for r in results:
        if isinstance(r, ScraperBrowserDeadError):
            raise r


async def _scrape_in_context(
    ctx, careers_url: str, base_domain: str, fetch_descriptions: bool = True,
    diag: Optional[dict] = None, partial: Optional[list] = None,
) -> list[dict]:
    """Opens the page, navigates, extracts links. Raises
    ScraperBrowserDeadError if the browser itself has died; ordinary
    per-page failures (timeouts, bad selectors) are the caller's job
    to log and treat as a soft failure."""
    from playwright.async_api import TimeoutError as PWTimeout

    try:
        page = await ctx.new_page()
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        print(f"[async_career_scraper] Could not open a page for {careers_url}: {e}")
        return []

    page.set_default_timeout(15_000)
    try:
        if diag is not None:
            diag["stage_reached"] = "goto"
        await page.goto(careers_url, timeout=20_000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        if diag is not None:
            diag["stage_reached"] = "extract_links"
        # Does this careers page embed a supported ATS (Greenhouse/Lever/Ashby/
        # Workable)? Those are usually in an iframe or injected script, which
        # link scraping can't see. Recorded so the orchestrator can prefer that
        # ATS's API; we skip the (slow) per-job description loads in that case.
        embedded = False
        if diag is not None:
            try:
                emb = _extract_ats_from_html(await page.content(), careers_url)
                if emb and emb.can_api and emb.token:
                    diag["embedded_ats"] = (emb.ats, emb.token)
                    embedded = True
            except Exception:
                pass

        jobs = await _extract_links(page, careers_url, base_domain, diag=diag)
        if partial is not None:
            # Hand the caller the links right away, so a hard timeout during the
            # (slow) description step no longer throws them all away.
            partial.extend(jobs)
        if diag is not None:
            diag["stage_reached"] = "job_descriptions"
            diag["links_before_descriptions"] = len(jobs)
        if fetch_descriptions and not embedded:
            await _fill_descriptions(ctx, jobs)
        return jobs
    except PWTimeout:
        print(f"[async_career_scraper] Timeout loading {careers_url}")
        if diag is not None:
            diag["outcome"] = "goto_timeout"
        return []
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        raise
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def _scrape_with_browser(
    browser, careers_url: str, base_domain: str, fetch_descriptions: bool = True,
    diag: Optional[dict] = None,
) -> list[dict]:
    """Scrape a careers page with hard timeout protection."""
    jobs = []
    partial: list[dict] = []   # links found so far; survives a hard timeout

    try:
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        print(f"[async_career_scraper] Could not open a browser context for {careers_url}: {e}")
        if diag is not None:
            diag["outcome"] = "context_error"
        return jobs

    try:
        try:
            # asyncio.timeout() is Python 3.11+; fall back to wait_for on older runtimes.
            async with asyncio.timeout(HARD_TIMEOUT_SECONDS):
                jobs = await _scrape_in_context(
                    ctx, careers_url, base_domain, fetch_descriptions=fetch_descriptions,
                    diag=diag, partial=partial,
                )
        except AttributeError:
            jobs = await asyncio.wait_for(
                _scrape_in_context(
                    ctx, careers_url, base_domain, fetch_descriptions=fetch_descriptions,
                    diag=diag, partial=partial,
                ),
                timeout=HARD_TIMEOUT_SECONDS,
            )
        if diag is not None:
            diag.setdefault("outcome", "ok")
    except ScraperBrowserDeadError:
        raise
    except asyncio.TimeoutError:
        print(f"[async_career_scraper] Hard timeout (>{HARD_TIMEOUT_SECONDS}s) on {careers_url}")
        if partial:
            # Keep the links we already found (some may lack a description).
            jobs = list(partial)
            print(f"[async_career_scraper] Kept {len(jobs)} link(s) found before the timeout on {careers_url}")
        if diag is not None:
            diag["outcome"] = "hard_timeout"
            diag["partial_jobs_kept"] = len(jobs)
    except Exception as e:
        print(f"[async_career_scraper] Error scraping {careers_url}: {e}")
        if diag is not None:
            diag["outcome"] = f"error: {e}"[:200]
    finally:
        try:
            await ctx.close()
        except Exception:
            pass

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Careers-page discovery (real browser)
#
# detect_ats() only ever looks for a careers page with plain `requests` calls
# (8 path guesses + 2 subdomains, HTTP 200 only). Sites that block non-browser
# clients, need JS, or keep careers under an unusual URL end up with no careers
# URL at all — and used to be dropped without a trace. This loads the homepage
# in the real browser and picks the best careers link from its anchors.
# (The previous version of this function was never called anywhere, and used
# locator.get_attribute(), which silently waits 30s per text pattern when
# nothing matches.)
# ─────────────────────────────────────────────────────────────────────────────

_ANCHOR_JS = """els => els.map(e => ({
    href: e.href || '',
    text: ((e.innerText || e.textContent || '').trim()).slice(0, 80),
    aria: (e.getAttribute('aria-label') || '').slice(0, 80)
}))"""

_CAREER_LINK_TEXT = re.compile(
    r"^\s*(careers?|jobs?|join( us| our team| the team)?|work (with|at|for) us|"
    r"open (positions|roles)|current openings|we'?re hiring|opportunities|employment|"
    r"explore careers|view (all )?jobs|search jobs|life at .{1,30})\s*[>›»]?\s*$",
    re.IGNORECASE,
)
_CAREER_TEXT_HINT = re.compile(r"career|job|hiring|join|openings", re.IGNORECASE)
_CAREER_HREF = re.compile(
    r"/(careers?|jobs?|join(-us)?|work-(with|at|for)-us|employment|opportunities|openings|open-positions)(/|$|\?|-)",
    re.IGNORECASE,
)
_BAD_LINK_HOSTS = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "tiktok.com", "glassdoor.com", "indeed.com", "wikipedia.org",
)
_KNOWN_ATS_HOSTS = (
    "greenhouse.io", "lever.co", "ashbyhq.com", "myworkdayjobs.com", "workable.com",
    "smartrecruiters.com", "icims.com", "bamboohr.com", "recruitee.com", "jobvite.com",
    "taleo.net", "rippling.com", "breezy.hr", "successfactors.com", "successfactors.eu",
    "ultipro.com", "paylocity.com", "dayforcehcm.com", "teamtailor.com", "personio.de",
    "personio.com", "eightfold.ai", "phenompeople.com", "zohorecruit.com", "zohorecruit.in",
)


def _host_matches(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def _pick_careers_link(anchors: list[dict], page_url: str) -> Optional[str]:
    """Choose the most likely careers link from a homepage's anchors, or None.
    Pure function (no browser) so it can be unit-tested."""
    page_base = (page_url or "").split("#")[0]
    best, best_score = None, 0
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href.startswith("http") or href.split("#")[0] == page_base:
            continue
        parsed = urlparse(href)
        host = parsed.netloc.lower().split(":")[0]
        if _host_matches(host, _BAD_LINK_HOSTS):
            continue
        text = (a.get("text") or a.get("aria") or "").strip()

        score = 0
        if _CAREER_LINK_TEXT.match(text):
            score += 3
        if _host_matches(host, _KNOWN_ATS_HOSTS):
            score += 3
        if _CAREER_HREF.search(parsed.path or ""):
            score += 1
            if _CAREER_TEXT_HINT.search(text):
                score += 1
        if score >= 2 and score > best_score:
            best, best_score = href, score
    return best


async def find_careers_url_via_playwright(base_url: str, browser=None,
                                          diag: Optional[dict] = None) -> Optional[str]:
    """Open the company homepage in the real browser and return its best
    careers link (see _pick_careers_link), or None.

    `diag` (diagnostics only) gets `outcome`: found | no_careers_link_on_homepage |
    homepage_load_failed: ... | no_website | error: ...
    Raises ScraperBrowserDeadError if the browser itself died."""
    if diag is None:
        diag = {}
    if not base_url:
        diag["outcome"] = "no_website"
        return None
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    owns_browser = browser is None
    pw = None
    if owns_browser:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            diag["outcome"] = "error: playwright not installed"
            return None
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )

    try:
        try:
            ctx = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
        except Exception as e:
            if is_dead_browser_error(e):
                raise ScraperBrowserDeadError(str(e)) from e
            diag["outcome"] = f"error: {e}"[:200]
            return None

        try:
            try:
                page = await ctx.new_page()
            except Exception as e:
                if is_dead_browser_error(e):
                    raise ScraperBrowserDeadError(str(e)) from e
                diag["outcome"] = f"error: {e}"[:200]
                return None
            try:
                await page.goto(base_url, timeout=20_000, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                anchors = await page.eval_on_selector_all("a[href]", _ANCHOR_JS)
                diag["anchors_seen"] = len(anchors)
                best = _pick_careers_link(anchors, page.url)
                diag["outcome"] = "found" if best else "no_careers_link_on_homepage"
                return best
            except ScraperBrowserDeadError:
                raise
            except Exception as e:
                if is_dead_browser_error(e):
                    raise ScraperBrowserDeadError(str(e)) from e
                diag["outcome"] = f"homepage_load_failed: {type(e).__name__}: {str(e)[:100]}"
                return None
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
        finally:
            try:
                await ctx.close()
            except Exception:
                pass
    finally:
        if owns_browser:
            try:
                await browser.close()
            except Exception:
                pass
            if pw is not None:
                try:
                    await pw.stop()
                except Exception:
                    pass


JOB_LINK_KEYWORDS = re.compile(
    r"(job|career|position|opening|role|apply|posting|opportunity|vacancy|recruit)",
    re.IGNORECASE,
)

NOISE_WORDS = re.compile(
    r"^(home|about|contact|blog|news|press|team|product|pricing|sign|log|"
    r"privacy|terms|cookie|back|next|prev|all jobs?|view all|see all|more|"
    r"careers?|apply( now)?|apply for job|learn more( and apply)?|"
    r"view (job|open roles?( now)?)|search jobs?|open positions?|"
    r"see (open )?(jobs?|roles?|positions?)|explore (jobs?|careers?)|"
    r"join (us|our team)|current openings?)[\s>]*$",
    re.IGNORECASE,
)

MAX_TITLE_WORDS = 8


def _job_link_reject_reason(href: str, text: str) -> Optional[str]:
    """None if the link looks like a job link, else a short reason code.
    (Same rules as before — split out so rejections can be diagnosed.)"""
    stripped = text.strip()
    if NOISE_WORDS.match(stripped):
        return "noise_word"
    if len(stripped) < 5 or len(stripped) > 150:
        return "title_length"
    if len(stripped.split()) > MAX_TITLE_WORDS:
        return "too_many_words"
    if not (JOB_LINK_KEYWORDS.search(href) or JOB_LINK_KEYWORDS.search(text)):
        return "no_job_keyword"
    return None


def _looks_like_job_link(href: str, text: str) -> bool:
    return _job_link_reject_reason(href, text) is None


def _clean_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[\s>»›\u2192]+$", "", cleaned).strip()