"""
Async Career Scraper — Playwright async API for fallback job scraping.

This replaces the sync API with native async/await, eliminating greenlet
context-switching issues and improving concurrency.

Returns the same normalized dict shape as ats_api.py:
  { title, department, location, apply_url, posted_at }
"""

import asyncio
import re
from typing import Optional
from urllib.parse import urljoin

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
    """
    if browser is not None:
        return await _scrape_with_browser(browser, careers_url, base_domain)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[async_career_scraper] Playwright not installed; skipping scrape.")
        return []

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        try:
            return await _scrape_with_browser(b, careers_url, base_domain)
        finally:
            await b.close()


async def _scrape_with_browser(browser, careers_url: str, base_domain: str) -> list[dict]:
    """Scrape a careers page with hard timeout protection."""
    from playwright.async_api import TimeoutError as PWTimeout

    jobs = []
    ctx = await browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    )

    try:
        # Wrap in asyncio.wait_for for hard cap (works on Python 3.11+)
        try:
            async with asyncio.timeout(HARD_TIMEOUT_SECONDS):
                page = await ctx.new_page()
                page.set_default_timeout(15_000)

                try:
                    await page.goto(careers_url, timeout=20_000, wait_until="domcontentloaded")
                    await page.wait_for_timeout(2000)

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
                            })
                        except Exception:
                            continue

                except PWTimeout:
                    print(f"[async_career_scraper] Timeout loading {careers_url}")
                except Exception as e:
                    print(f"[async_career_scraper] Error scraping {careers_url}: {e}")
                finally:
                    await page.close()

        except AttributeError:
            # Python < 3.11: use asyncio.wait_for instead of asyncio.timeout
            page = await ctx.new_page()
            page.set_default_timeout(15_000)

            try:
                await asyncio.wait_for(
                    page.goto(careers_url, timeout=20_000, wait_until="domcontentloaded"),
                    timeout=HARD_TIMEOUT_SECONDS
                )
                await page.wait_for_timeout(2000)

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
                        })
                    except Exception:
                        continue
            except asyncio.TimeoutError:
                print(f"[async_career_scraper] Hard timeout (>{HARD_TIMEOUT_SECONDS}s) on {careers_url}")
            finally:
                await page.close()

    except Exception as e:
        print(f"[async_career_scraper] Context error on {careers_url}: {e}")
    finally:
        await ctx.close()

    return jobs


async def find_careers_url_via_playwright(base_url: str, browser=None) -> Optional[str]:
    """Navigate the company homepage and find the careers link."""
    owns_browser = browser is None
    if owns_browser:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return None
        pw = async_playwright().__aenter__()
        browser = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
    else:
        pw = None

    ctx = await browser.new_context()
    page = await ctx.new_page()
    href_found = None
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
        await ctx.close()
        if owns_browser:
            await browser.close()

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

