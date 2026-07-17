"""
Career Scraper — Playwright-based fallback for companies whose jobs
are not on a supported ATS. Navigates to the careers page and
extracts job listings via DOM inspection.

Returns the same normalized dict shape as ats_api.py:
  { title, department, location, apply_url, posted_at }

Perf note: the original version called `pw.chromium.launch()` fresh
for every single company. Browser launch is ~1-3s on its own, before
any navigation happens — for a batch with 100 companies needing scrape
fallback, that's 100-300s spent just starting browsers.

`scrape_careers_page` now accepts an already-running `browser` object
(a persistent Playwright Chromium instance, one per worker thread —
see agent/browser_pool.py). It opens a fresh *page* per company
(cheap, milliseconds) instead of a fresh *browser* (expensive, seconds).
If no browser is passed in, it falls back to the old launch-per-call
behavior so this module still works standalone.
"""

import re
import threading
from typing import Optional
from urllib.parse import urljoin

# Hard wall-clock cap on top of Playwright's own per-call timeouts. Belt and
# suspenders: page.goto() already has a 20s timeout, but that alone doesn't
# bound the whole function — a page that loads fine and then hangs on
# something else (an unhandled JS dialog, a stuck client-side redirect, a
# context.close() that blocks on a pending download) has nothing forcing it
# to give up. This watchdog force-closes the browser context once the cap is
# hit, which raises inside whatever Playwright call is in-flight and
# unblocks it — guaranteeing _scrape_with_browser always returns.
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


def scrape_careers_page(careers_url: str, base_domain: str, browser=None) -> list[dict]:
    """
    Navigate to a careers page and extract job links.

    `browser`: an already-launched playwright Chromium browser (reused
    across many companies). If None, launches (and closes) a throwaway
    browser for this call only — slower, kept for standalone use.
    """
    if browser is not None:
        return _scrape_with_browser(browser, careers_url, base_domain)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[career_scraper] Playwright not installed; skipping scrape.")
        return []

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        try:
            return _scrape_with_browser(b, careers_url, base_domain)
        finally:
            b.close()


def _scrape_with_browser(browser, careers_url: str, base_domain: str) -> list[dict]:
    from playwright.sync_api import TimeoutError as PWTimeout

    jobs = []
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )

    # Watchdog: if this company isn't done within HARD_TIMEOUT_SECONDS,
    # force-close the context so whatever's blocking (goto, an element call,
    # ctx.close() itself) gets interrupted instead of hanging indefinitely.
    watchdog = threading.Timer(HARD_TIMEOUT_SECONDS, lambda: _force_close(ctx))
    watchdog.daemon = True
    watchdog.start()

    page = ctx.new_page()
    page.set_default_timeout(15_000)  # catches any action call not given an explicit timeout below

    try:
        page.goto(careers_url, timeout=20_000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)  # let JS render

        links = []
        for sel in LISTING_SELECTORS:
            try:
                els = page.query_selector_all(sel)
                if els:
                    links = els
                    break
            except Exception:
                continue

        if not links:
            links = page.query_selector_all("a[href]")

        seen_hrefs = set()
        for el in links:
            try:
                href = el.get_attribute("href") or ""
                text = (el.inner_text() or "").strip()

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
                })
            except Exception:
                continue

    except PWTimeout:
        print(f"[career_scraper] Timeout loading {careers_url}")
    except Exception as e:
        print(f"[career_scraper] Error scraping {careers_url}: {e}")
    finally:
        watchdog.cancel()
        _force_close(ctx)  # no-op if the watchdog already closed it

    return jobs


def _force_close(ctx) -> None:
    try:
        ctx.close()
    except Exception:
        pass  # already closed (by us or by the watchdog) — fine either way


def find_careers_url_via_playwright(base_url: str, browser=None) -> Optional[str]:
    """Navigate the company homepage and find the careers link."""
    owns_browser = browser is None
    if owns_browser:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
    else:
        pw = None

    ctx = browser.new_context()
    page = ctx.new_page()
    href_found = None
    try:
        page.goto(base_url, timeout=20_000, wait_until="domcontentloaded")
        for text_pattern in ["careers", "jobs", "join us", "work with us", "open positions"]:
            try:
                link = page.get_by_text(re.compile(text_pattern, re.IGNORECASE)).first
                href = link.get_attribute("href")
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
        ctx.close()
        if owns_browser:
            browser.close()
            pw.stop()

    return href_found


JOB_LINK_KEYWORDS = re.compile(
    r"(job|career|position|opening|role|apply|posting|opportunity|vacancy|recruit)",
    re.IGNORECASE,
)

NOISE_WORDS = re.compile(
    r"^(home|about|contact|blog|news|press|team|product|pricing|sign|log|"
    r"privacy|terms|cookie|back|next|prev|all jobs?|view all|see all|more)$",
    re.IGNORECASE,
)


def _looks_like_job_link(href: str, text: str) -> bool:
    if NOISE_WORDS.match(text.strip()):
        return False
    if len(text) < 5 or len(text) > 150:
        return False
    return bool(JOB_LINK_KEYWORDS.search(href) or JOB_LINK_KEYWORDS.search(text))


def _clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()