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
from typing import Optional
from urllib.parse import urljoin

from .scraper_errors import ScraperBrowserDeadError, is_dead_browser_error
from .text_extract import DESCRIPTION_SNIPPET_CHARS, make_snippet

# Hard wall-clock cap on top of Playwright's own per-call timeouts.
HARD_TIMEOUT_SECONDS = 45

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


async def scrape_careers_page(careers_url: str, base_domain: str, browser=None) -> list[dict]:
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
        return await _scrape_with_browser(browser, careers_url, base_domain)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[async_career_scraper] Playwright not installed; skipping scrape.")
        return []

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        try:
            return await _scrape_with_browser(b, careers_url, base_domain)
        finally:
            await b.close()


async def _extract_links(page, careers_url: str, base_domain: str) -> list[dict]:
    """Shared link-extraction logic."""
    jobs = []
    links = []
    for sel in LISTING_SELECTORS:
        try:
            els = await page.query_selector_all(sel)
            if els:
                links = els
                break
        except Exception:
            continue

    if not links:
        links = await page.query_selector_all("a[href]")

    seen_hrefs = set()
    for el in links:
        try:
            href = await el.get_attribute("href") or ""
            text = (await el.inner_text() or "").strip()

            if not text or not href:
                continue

            if href.startswith("/"):
                href = base_domain.rstrip("/") + href
            elif not href.startswith("http"):
                href = urljoin(careers_url, href)

            if not _looks_like_job_link(href, text):
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


async def _scrape_in_context(
    ctx, careers_url: str, base_domain: str, fetch_descriptions: bool = True
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
        await page.goto(careers_url, timeout=20_000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2000)
        jobs = await _extract_links(page, careers_url, base_domain)
        if fetch_descriptions:
            for job in jobs:
                if job["apply_url"]:
                    job["description_snippet"] = await _fetch_job_description_snippet(
                        ctx, job["apply_url"]
                    )
        return jobs
    except PWTimeout:
        print(f"[async_career_scraper] Timeout loading {careers_url}")
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
    browser, careers_url: str, base_domain: str, fetch_descriptions: bool = True
) -> list[dict]:
    """Scrape a careers page with hard timeout protection."""
    jobs = []

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
        return jobs

    try:
        try:
            # asyncio.timeout() is Python 3.11+; fall back to wait_for on older runtimes.
            async with asyncio.timeout(HARD_TIMEOUT_SECONDS):
                jobs = await _scrape_in_context(
                    ctx, careers_url, base_domain, fetch_descriptions=fetch_descriptions
                )
        except AttributeError:
            jobs = await asyncio.wait_for(
                _scrape_in_context(
                    ctx, careers_url, base_domain, fetch_descriptions=fetch_descriptions
                ),
                timeout=HARD_TIMEOUT_SECONDS,
            )
    except ScraperBrowserDeadError:
        raise
    except asyncio.TimeoutError:
        print(f"[async_career_scraper] Hard timeout (>{HARD_TIMEOUT_SECONDS}s) on {careers_url}")
    except Exception as e:
        print(f"[async_career_scraper] Error scraping {careers_url}: {e}")
    finally:
        try:
            await ctx.close()
        except Exception:
            pass

    return jobs


async def find_careers_url_via_playwright(base_url: str, browser=None) -> Optional[str]:
    """Navigate the company homepage and find the careers link."""
    owns_browser = browser is None
    pw = None
    if owns_browser:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])

    href_found = None
    try:
        ctx = await browser.new_context()
        try:
            page = await ctx.new_page()
            try:
                await page.goto(base_url, timeout=20_000, wait_until="domcontentloaded")
                for text_pattern in ["careers", "jobs", "join us", "work with us", "open positions"]:
                    try:
                        link = page.get_by_text(re.compile(text_pattern, re.IGNORECASE)).first
                        href = await link.get_attribute("href")
                        if href:
                            if href.startswith("/"):
                                href = base_url.rstrip("/") + href
                            href_found = href
                            break
                    except Exception:
                        continue
            except Exception:
                pass
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

    return href_found


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


def _looks_like_job_link(href: str, text: str) -> bool:
    stripped = text.strip()
    if NOISE_WORDS.match(stripped):
        return False
    if len(stripped) < 5 or len(stripped) > 150:
        return False
    if len(stripped.split()) > MAX_TITLE_WORDS:
        return False
    return bool(JOB_LINK_KEYWORDS.search(href) or JOB_LINK_KEYWORDS.search(text))


def _clean_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[\s>»›\u2192]+$", "", cleaned).strip()