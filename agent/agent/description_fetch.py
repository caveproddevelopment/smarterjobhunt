"""
Description fetching for run_description_backfill.py (added 2026-10-15).

One job at a time, from its apply_url:
  1. The hiring platform's API, when the URL belongs to one we know
     (Workday, SmartRecruiters, Oracle, Workable, Greenhouse, Lever) —
     see ats_api.detail_for_url().
  2. Otherwise the job page itself with plain HTTP: a schema.org
     JobPosting description (JSON-LD) if the page has one, else the main
     content area, else the page text.
  3. If that gives fewer than MIN_DESCRIPTION_CHARS (a JavaScript page that
     renders client-side), the page is rendered in headless Chromium and
     step 2's extraction runs on the rendered HTML.

Outcomes are FetchResult(ok, text, source, error, transient). `transient`
marks failures that say nothing about the link itself (HTTP 429, 5xx,
timeouts); the backfill doesn't count those against a link's 3 tries.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Optional

import requests

from . import ats_api
from .text_extract import DESCRIPTION_SNIPPET_CHARS, make_snippet

MIN_DESCRIPTION_CHARS = 100   # same bar as the backend's auto-approve rule
PAGE_TIMEOUT = 20
RENDER_TIMEOUT_MS = 25_000

PAGE_HEADERS = {
    **ats_api.HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_CONTENT_SELECTORS = [
    "[itemprop='description']",
    "[class*='job-description' i]", "[class*='jobdescription' i]", "[id*='job-description' i]",
    "[class*='job_description' i]", "[id*='jobdescription' i]",
    "[class*='description' i]", "[id*='description' i]",
    "article", "main", "[role='main']",
]


@dataclass
class FetchResult:
    ok: bool
    text: str = ""
    source: str = ""          # workday / oracle / ... / page / page_rendered
    error: str = ""
    transient: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# HTML extraction
# ─────────────────────────────────────────────────────────────────────────────

def _jsonld_objects(html: str):
    for m in re.finditer(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
                         html, re.I | re.S):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, list):
                stack.extend(o)
            elif isinstance(o, dict):
                yield o
                if "@graph" in o:
                    stack.append(o["@graph"])


def jobposting_description(html: str) -> str:
    """The description from a schema.org JobPosting JSON-LD block, or ""."""
    for o in _jsonld_objects(html or ""):
        t = o.get("@type")
        types = t if isinstance(t, list) else [t]
        if "JobPosting" in types and isinstance(o.get("description"), str):
            return make_snippet(o["description"], is_html=True)
    return ""


def extract_description(html: str) -> str:
    """Best description text from a job page's HTML (JSON-LD first, then the
    main content area, then the whole page), cut to DESCRIPTION_SNIPPET_CHARS."""
    if not html:
        return ""
    d = jobposting_description(html)
    if len(d) >= MIN_DESCRIPTION_CHARS:
        return d
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "header", "footer", "form", "svg"]):
            tag.decompose()
        best = ""
        for sel in _CONTENT_SELECTORS:
            for el in soup.select(sel)[:5]:
                text = make_snippet(str(el), is_html=True)
                if len(text) > len(best):
                    best = text
            if len(best) >= MIN_DESCRIPTION_CHARS:
                return best
        body = soup.body or soup
        whole = make_snippet(str(body), is_html=True)
        return whole if len(whole) > len(best) else best
    except Exception:
        return make_snippet(html, is_html=True, max_chars=DESCRIPTION_SNIPPET_CHARS)


def _is_transient_status(code: Optional[int]) -> bool:
    return code is not None and (code == 429 or code >= 500)


def _http_error(e: Exception) -> tuple[str, bool]:
    resp = getattr(e, "response", None)
    code = getattr(resp, "status_code", None)
    if code is not None:
        return f"http_{code}", _is_transient_status(code)
    transient = isinstance(e, (requests.Timeout, requests.ConnectionError))
    return f"{type(e).__name__}: {e}"[:200], transient


# ─────────────────────────────────────────────────────────────────────────────
# Fetchers
# ─────────────────────────────────────────────────────────────────────────────

def fetch_via_api(apply_url: str) -> Optional[FetchResult]:
    """Platform API step. None when no API covers this URL."""
    try:
        got = ats_api.detail_for_url(apply_url)
    except Exception as e:
        err, transient = _http_error(e)
        source = ats_api.detail_source_for_url(apply_url) or "api"
        return FetchResult(False, source=source, error=err, transient=transient)
    if got is None:
        return None
    source, text = got
    if len(text) >= MIN_DESCRIPTION_CHARS:
        return FetchResult(True, text=text, source=source)
    return FetchResult(False, text=text, source=source, error="too_short")


def fetch_page_html(apply_url: str) -> tuple[Optional[str], Optional[FetchResult]]:
    """Plain-HTTP page fetch. (html, None) on success, (None, failure)."""
    try:
        r = requests.get(apply_url, headers=PAGE_HEADERS, timeout=PAGE_TIMEOUT, allow_redirects=True)
    except Exception as e:
        err, transient = _http_error(e)
        return None, FetchResult(False, source="page", error=err, transient=transient)
    if r.status_code != 200:
        return None, FetchResult(False, source="page", error=f"http_{r.status_code}",
                                 transient=_is_transient_status(r.status_code))
    ctype = r.headers.get("Content-Type", "")
    if ctype and "html" not in ctype.lower():
        return None, FetchResult(False, source="page", error=f"not_html ({ctype[:40]})")
    return r.text, None


class Renderer:
    """Lazily launched shared headless Chromium for JavaScript job pages."""

    def __init__(self, max_pages: int = 4):
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()
        self._sem = asyncio.Semaphore(max_pages)
        self.available = True

    async def _ensure(self):
        async with self._lock:
            if self._browser is not None or not self.available:
                return
            try:
                from playwright.async_api import async_playwright
                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
            except Exception as e:
                print(f"[description_fetch] headless browser unavailable: {e}", flush=True)
                self.available = False

    async def render(self, url: str) -> tuple[Optional[str], str]:
        await self._ensure()
        if not self.available:
            return None, "no_browser"
        async with self._sem:
            ctx = await self._browser.new_context(user_agent=ats_api.HEADERS["User-Agent"])
            try:
                page = await ctx.new_page()
                resp = await page.goto(url, timeout=RENDER_TIMEOUT_MS, wait_until="domcontentloaded")
                if resp is not None and resp.status >= 400:
                    return None, f"http_{resp.status}"
                try:
                    await page.wait_for_load_state("networkidle", timeout=6_000)
                except Exception:
                    pass
                return await page.content(), ""
            except Exception as e:
                return None, f"render_{type(e).__name__}"[:200]
            finally:
                await ctx.close()

    async def close(self):
        try:
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()
        except Exception:
            pass


async def fetch_description(apply_url: str, renderer: Optional[Renderer]) -> FetchResult:
    """API, then page, then rendered page. Never raises."""
    api = await asyncio.to_thread(fetch_via_api, apply_url)
    if api is not None:
        return api

    html, fail = await asyncio.to_thread(fetch_page_html, apply_url)
    if fail is not None and (fail.error.startswith("not_html") or fail.error in ("http_404", "http_410")
                             or renderer is None):
        return fail
    text = extract_description(html) if html else ""
    if len(text) >= MIN_DESCRIPTION_CHARS:
        return FetchResult(True, text=text, source="page")

    # Fewer than 100 chars (or a blocked plain fetch): render it.
    if renderer is None:
        return FetchResult(False, text=text, source="page", error="too_short")
    rendered, err = await renderer.render(apply_url)
    if rendered is None:
        if fail is not None:
            return fail
        return FetchResult(False, source="page_rendered", error=err or "render_failed",
                           transient=err == "no_browser")
    text = extract_description(rendered)
    if len(text) >= MIN_DESCRIPTION_CHARS:
        return FetchResult(True, text=text, source="page_rendered")
    return FetchResult(False, text=text, source="page_rendered", error="too_short")
