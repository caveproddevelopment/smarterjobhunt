"""
Career Scraper — Playwright-based fallback for companies whose jobs
are not on a supported ATS. Navigates to the careers page and
extracts job listings via DOM inspection.

Returns the same normalized dict shape as ats_api.py:
  { title, department, location, apply_url, posted_at, description_snippet }

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

Description-snippet capture (added 2026-08-19): this is the most
expensive of the four data sources for descriptions. The listing page
only ever had title + link — there was never a description available
here for free. Getting one means visiting every individual job's page,
one extra Playwright navigation per job found, on top of the one
navigation this function already does for the listing page itself. For
a company with 20 open roles, that's 20 extra page loads instead of 1.
This runs sequentially within the calling worker thread (no added
threading here, to keep the change easy to reason about and roll back)
so it directly extends how long a scrape-fallback company takes — see
the evaluation note in the project doc about measuring this against a
real batch before enabling broadly. Set `fetch_descriptions=False` to
skip it and keep the original title/link-only behavior.

Reliability fixes (2026-08-24, after a driver crash ~94% through a
1923-company run):
  - `browser.new_context()` and `ctx.new_page()` (both here and inside
    the per-job description fetch) used to sit outside the try/finally
    that closes the context. If either call raised, the context leaked
    for the rest of the run instead of being cleaned up — one
    contributor to the resource growth that eventually crashed the
    shared browser's driver process near the end of a large batch.
  - When the browser's underlying driver connection has actually died
    (as opposed to an ordinary per-company failure like a page
    timeout), that's now detected and raised as `ScraperBrowserDeadError`
    instead of being logged and swallowed. Swallowing it used to mean
    every remaining company on that thread silently scored 0 jobs for
    the rest of the run, indistinguishable in the logs from companies
    that genuinely have no listed jobs. `ingestion_orchestrator.py`
    catches this specifically, discards the dead browser, and retries
    with a fresh one.
  - Added an explicit `page.set_default_timeout()` so a stuck selector
    query can't hang a worker thread indefinitely.

Content-quality fixes (2026-08-31, from the jobs_staging QA review):
  - `NOISE_WORDS` now covers career-page CTA/button language ("Apply
    Now", "Learn more and apply", "View open roles now", etc.), not
    just generic sitewide nav — see the comment above `NOISE_WORDS`
    for the staging-table frequency counts that drove this list.
  - `_looks_like_job_link` adds a `MAX_TITLE_WORDS` ceiling as a second,
    structural filter layer: real job titles are short phrases, not
    full sentences, which catches CTA phrasing the blocklist hasn't
    seen yet without needing to enumerate it by hand.
  - `_clean_title` strips trailing chevron/arrow characters some sites
    use as decorative CTA styling (e.g. "Learn more >").
These are layered on top of the 2026-08-24 reliability fixes above —
both sets of changes are active in this version.
"""

import re
import time
from typing import Optional
from urllib.parse import urljoin

from .text_extract import html_to_text, make_snippet, DESCRIPTION_SNIPPET_CHARS
from .scraper_errors import ScraperBrowserDeadError, is_dead_browser_error

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


def scrape_careers_page(careers_url: str, base_domain: str, browser=None, fetch_descriptions: bool = True) -> list[dict]:
    """
    Navigate to a careers page and extract job links.

    `browser`: an already-launched playwright Chromium browser (reused
    across many companies). If None, launches (and closes) a throwaway
    browser for this call only — slower, kept for standalone use.
    `fetch_descriptions`: when True (default), visit each job's own page
    to pull a description snippet — see the module docstring for the
    real per-job cost this adds. False restores the original
    title/link-only behavior with no extra navigations.

    Raises `ScraperBrowserDeadError` if the browser's driver connection
    has died. Callers using a shared/pooled browser should catch this
    specifically, discard the browser, and retry with a fresh one
    rather than treating it as an ordinary per-company failure.
    """
    if browser is not None:
        return _scrape_with_browser(browser, careers_url, base_domain, fetch_descriptions=fetch_descriptions)

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[career_scraper] Playwright not installed; skipping scrape.")
        return []

    with sync_playwright() as pw:
        b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        try:
            return _scrape_with_browser(b, careers_url, base_domain, fetch_descriptions=fetch_descriptions)
        finally:
            b.close()


def _fetch_job_description_snippet(ctx, url: str, timeout_seconds: float = 15) -> str:
    """One extra page load per job — see the cost note in the module
    docstring. Opens its own page in the given (already-open) context,
    reads the rendered HTML, cleans it, and closes the page. Fails soft
    (returns "") on an ordinary timeout or page-level error, but raises
    `ScraperBrowserDeadError` if the browser itself has died — that's
    not this one job's problem, it's every remaining job's problem.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        page = ctx.new_page()
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return ""

    try:
        page.goto(url, timeout=max(1, int(timeout_seconds * 1000)), wait_until="domcontentloaded")
        page.wait_for_timeout(1000)  # let JS render, shorter than the listing-page wait since this is a single job page
        html = page.content()
        return make_snippet(html, is_html=True, max_chars=DESCRIPTION_SNIPPET_CHARS)
    except PWTimeout:
        return ""
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return ""
    finally:
        try:
            page.close()
        except Exception:
            pass


def _scrape_with_browser(browser, careers_url: str, base_domain: str, fetch_descriptions: bool = True) -> list[dict]:
    from playwright.sync_api import TimeoutError as PWTimeout

    jobs = []
    deadline = time.monotonic() + HARD_TIMEOUT_SECONDS

    try:
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        print(f"[career_scraper] Could not open a browser context for {careers_url}: {e}")
        return jobs

    try:
        try:
            page = ctx.new_page()
        except Exception as e:
            if is_dead_browser_error(e):
                raise ScraperBrowserDeadError(str(e)) from e
            print(f"[career_scraper] Could not open a page for {careers_url}: {e}")
            return jobs

        try:
            page.set_default_timeout(15_000)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return jobs
            page.goto(careers_url, timeout=max(1, int(min(20, remaining) * 1000)), wait_until="domcontentloaded")
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
                        "title":               _clean_title(text),
                        "department":          "",
                        "location":            "",
                        "apply_url":           href,
                        "posted_at":           "",
                        "description_snippet": "",
                    })
                except Exception:
                    continue

            if fetch_descriptions:
                # Sequential, one extra page load per job — see module docstring.
                for job in jobs:
                    if job["apply_url"]:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        job["description_snippet"] = _fetch_job_description_snippet(
                            ctx, job["apply_url"], timeout_seconds=min(15, remaining)
                        )

        except PWTimeout:
            print(f"[career_scraper] Timeout loading {careers_url}")
        except ScraperBrowserDeadError:
            raise
        except Exception as e:
            print(f"[career_scraper] Error: {e}")
        finally:
            try:
                page.close()
            except Exception:
                pass

    finally:
        try:
            ctx.close()  # closes the context/page; browser itself stays alive for reuse
        except Exception:
            pass

    return jobs


def find_careers_url_via_playwright(base_url: str, browser=None) -> Optional[str]:
    """Navigate the company homepage and find the careers link."""
    owns_browser = browser is None
    pw = None
    if owns_browser:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return None
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])

    href_found = None
    try:
        ctx = browser.new_context()
        try:
            page = ctx.new_page()
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
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            try:
                ctx.close()
            except Exception:
                pass
    except Exception:
        pass
    finally:
        if owns_browser:
            try:
                browser.close()
            except Exception:
                pass
            if pw is not None:
                try:
                    pw.stop()
                except Exception:
                    pass

    return href_found


JOB_LINK_KEYWORDS = re.compile(
    r"(job|career|position|opening|role|apply|posting|opportunity|vacancy|recruit)",
    re.IGNORECASE,
)

# Fix for jobs_staging QA issue 1 (2026-08-31 review): the original list
# only covered generic sitewide nav ("home", "about"...) and never covered
# career-page-specific CTA/button language. Since nearly every link on a
# careers page has "career" or "job" IN ITS URL (it's the careers page),
# the href half of the OR check in _looks_like_job_link is almost always
# true — this blocklist was, in practice, the only real filter. These
# additions are the literal top offenders from the staging-table review
# (478x "Careers", 157x "Apply Now", 108x "CAREERS", ~199x "Learn more"
# variants, 86x "Apply for job", 60x "APPLY NOW", 51x "View open roles
# now", 41x "Search Jobs", 38x "Learn more and apply", 25x "View Job").
NOISE_WORDS = re.compile(
    r"^(home|about|contact|blog|news|press|team|product|pricing|sign|log|"
    r"privacy|terms|cookie|back|next|prev|all jobs?|view all|see all|more|"
    r"careers?|apply( now)?|apply for job|learn more( and apply)?|"
    r"view (job|open roles?( now)?)|search jobs?|open positions?|"
    r"see (open )?(jobs?|roles?|positions?)|explore (jobs?|careers?)|"
    r"join (us|our team)|current openings?)[\s>]*$",
    re.IGNORECASE,
)

# Fix for QA issue 5 (systemic, spread across nearly every company): the
# blocklist above will always be incomplete — every company phrases CTAs
# a little differently, and this will always be a step behind whatever
# new phrasing the next scraped company uses. This is a structural
# second layer, not a blocklist entry: real job titles are short phrases
# ("Senior Software Engineer"), not full sentences ("Learn more about
# opportunities on our team"). A word-count ceiling catches CTA phrasing
# the blocklist hasn't seen yet, without needing to enumerate it by hand.
MAX_TITLE_WORDS = 8


def _looks_like_job_link(href: str, text: str) -> bool:
    stripped = text.strip()
    if NOISE_WORDS.match(stripped):
        return False
    if len(stripped) < 5 or len(stripped) > 150:
        return False
    # Fix for QA issue 2 (full description paragraphs landing in the
    # title field): the old length check only rejected text over 150
    # characters, but the staging review flagged junk as short as ~100
    # characters — sentence fragments and CTA phrases that are short
    # enough to slip the character check but aren't shaped like a job
    # title. Word count is a tighter, more reliable signal than raw
    # character length for "does this look like a title."
    if len(stripped.split()) > MAX_TITLE_WORDS:
        return False
    return bool(JOB_LINK_KEYWORDS.search(href) or JOB_LINK_KEYWORDS.search(text))


def _clean_title(text: str) -> str:
    # Fix for QA issue 3: strips any literal trailing chevron/arrow
    # characters some sites use as decorative CTA styling (e.g. "Learn
    # more >"), in addition to the existing whitespace collapse. This is
    # a real characteristic of the site's own visible button text, not
    # unstripped HTML markup — Playwright's inner_text() already reads
    # rendered text, not raw HTML, so entities like "&gt;" would not
    # normally survive into this string unless the character is
    # literally visible on the page.
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"[\s>»›\u2192]+$", "", cleaned).strip()
    return cleaned