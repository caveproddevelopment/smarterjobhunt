"""
Async Career Scraper — Playwright async API for fallback job scraping.

Returns the same normalized dict shape as ats_api.py:
  { title, department, location, apply_url, posted_at, description_snippet }

Reliability fixes (2026-08-24): see git history / previous docstring —
dead-browser errors raise ScraperBrowserDeadError so the orchestrator can
relaunch; one shared _scrape_in_context() covers both timeout branches.

2026-10-13 changes (7 Oct India run, indian_companies_zero_jobs_findings.csv):
  - Page validation. After loading, the page is checked with
    platforms.classify_page(): images, 404s served as 200, error routes,
    login pages, parked domains, age gates, bot walls, redirects home or to
    an unrelated site, and pages with no careers wording at all are
    rejected (diag outcome "invalid_page", reason in diag["page_invalid"])
    instead of being scraped for junk links. 59 companies had a wrong page
    accepted; 58 produced "jobs" that were nav junk.
  - Hiring-platform hand-off. The final URL after redirects, every iframe,
    and outbound links pointing at a known hiring-platform host are
    recorded in diag["platform_urls"]; the orchestrator follows them
    (API if we have an adapter, else a second scrape on the platform page).
  - iframes. Links are collected from every frame, not just the main one
    (ZingHR, Kula, Recruiterbox, PyjamaHR, Dover, Keka embeds).
  - JSON capture. XHR/fetch JSON responses are recorded while the page
    loads and job_json.harvest_jobs_from_json() pulls job lists out of them
    — this is what gets jobs off JavaScript job boards (Darwinbox, Keka,
    PeopleStrong, SenseHQ, ...) whose listings aren't plain links.
  - One-shot link collection. All anchors are read in a single in-page JS
    call per frame (was two awaits per anchor — a page with 1,069 anchors
    like Ceat's spent the whole 45s budget just reading links), capped at
    MAX_ANCHORS_PER_FRAME.
  - Smarter waits. networkidle (bounded) instead of a fixed 2s, plus one
    extra wait when the page is still a near-empty JS shell.
  - Link filter. Links whose text is just "Apply" / "View job" / "Read more"
    are kept when the URL is a job-detail URL, titled from the job card's
    heading (or the URL slug). Whole-card link text is reduced to its
    heading / first line. More nav noise ("Life at X", "Benefits", ...) is
    rejected. The selector group that yields the most jobs wins (was: the
    first selector with any match).
  - HTTP/2 protocol errors (Akamai-fronted sites: Honeywell, Yes Bank,
    Policybazaar, EA, ...) are reported as outcome "http2_error" so the
    orchestrator can retry on an HTTP/1.1 browser.
"""

import asyncio
import re
import time
from typing import Optional
from urllib.parse import urlparse, unquote

from .ats_detector import _extract_ats_from_html
from .platforms import (
    classify_page, platform_for_url, parse_ats_url, API_ATS, host_of, host_matches,
    NON_CAREERS_HOSTS, unescape_for_scan,
)
from .job_json import harvest_jobs_from_json
from .scraper_errors import ScraperBrowserDeadError, is_dead_browser_error
from .text_extract import DESCRIPTION_SNIPPET_CHARS, make_snippet

# Hard wall-clock cap on top of Playwright's own per-call timeouts.
HARD_TIMEOUT_SECONDS = 70        # raised from 50 (2026-10-14) to make room for pagination

# Pagination (2026-10-14): after page 1, click "Load more" / "Next" / arrow /
# the next page number until no new jobs appear. Bounded by pages and time.
PAGINATION_MAX_PAGES = 15        # pages/clicks after the first one
PAGINATION_BUDGET_SECONDS = 25   # total time spent paginating one listing
PAGINATION_SETTLE_MS = 4000      # networkidle wait after each click (upper bound)
PAGINATION_STALE_LIMIT = 2       # stop after this many clicks in a row add no new jobs

MAX_DESCRIPTION_FETCHES = 60
DESCRIPTION_CONCURRENCY = 3
DESCRIPTION_BUDGET_SECONDS = 20

NETWORKIDLE_WAIT_MS = 6000       # upper bound; most pages go idle much sooner
EMPTY_SHELL_EXTRA_WAIT_MS = 3000
MAX_ANCHORS_PER_FRAME = 1500
MAX_FRAMES = 8
MAX_JSON_RESPONSES = 40
MAX_JSON_BYTES = 5_000_000

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
CONTEXT_OPTIONS = dict(
    user_agent=USER_AGENT,
    locale="en-US",
    viewport={"width": 1366, "height": 900},
    extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
)

LISTING_SELECTORS = [
    "a[href*='/job']",
    "a[href*='/jobs/']",
    "a[href*='/careers/']",
    "a[href*='/position']",
    "a[href*='/opening']",
    "a[href*='/apply']",
    "a[href*='vacanc']",
    "a[href*='requisition']",
    ".job-listing a",
    ".job-title a",
    ".careers-listing a",
    ".open-position a",
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


async def new_context(browser):
    return await browser.new_context(**CONTEXT_OPTIONS)


async def scrape_careers_page(careers_url: str, base_domain: str, browser=None,
                              diag: Optional[dict] = None, company_host: str = "") -> list[dict]:
    """
    Navigate to a careers page and extract jobs (async version).

    `browser`: an already-launched playwright async Chromium browser.
    If None, launches one for this call only.
    `company_host`: the company's own website host, used by page validation
    to tell a legitimate careers subdomain/brand site from an unrelated one.

    Raises `ScraperBrowserDeadError` if the browser's driver connection
    has died.
    """
    if browser is not None:
        return await _scrape_with_browser(browser, careers_url, base_domain, diag=diag,
                                          company_host=company_host)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("[async_career_scraper] Playwright not installed; skipping scrape.")
        return []

    async with async_playwright() as pw:
        b = await pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])
        try:
            return await _scrape_with_browser(b, careers_url, base_domain, diag=diag,
                                              company_host=company_host)
        finally:
            await b.close()


# ─────────────────────────────────────────────────────────────────────────────
# In-page JS
# ─────────────────────────────────────────────────────────────────────────────

_COLLECT_JS = r"""([sels, maxN]) => {
  const out = [];
  const as = document.querySelectorAll('a[href]');
  const cardSel = 'li,article,tr,[class*="job" i],[class*="card" i],[class*="opening" i],' +
                  '[class*="position" i],[class*="vacanc" i],[class*="role" i],[class*="listing" i]';
  const headSel = 'h1,h2,h3,h4,h5,h6,[class*="title" i],[class*="name" i],[class*="designation" i]';
  for (const a of as) {
    if (out.length >= maxN) break;
    let si = -1;
    for (let i = 0; i < sels.length; i++) { try { if (a.matches(sels[i])) { si = i; break; } } catch (e) {} }
    const text = ((a.innerText || a.textContent || '').trim()).slice(0, 400);
    let card = '';
    const h = a.querySelector(headSel);
    if (h) card = (h.innerText || h.textContent || '').trim();
    if (!card) {
      const c = a.parentElement ? a.parentElement.closest(cardSel) : null;
      if (c) {
        const hh = c.querySelector(headSel) || c.querySelector('strong,b');
        if (hh && hh !== a) card = (hh.innerText || hh.textContent || '').trim();
      }
    }
    out.push({href: a.href || '', text: text, card: card.slice(0, 200),
              aria: (a.getAttribute('aria-label') || a.getAttribute('title') || '').slice(0, 200), sel: si});
  }
  return out;
}"""

_META_JS = r"""() => ({
  title: document.title || '',
  h1: ((document.querySelector('h1') || {}).innerText || '').trim().slice(0, 200),
  text: ((document.body || {}).innerText || '').slice(0, 8000),
  anchors: document.querySelectorAll('a[href]').length,
  iframes: Array.from(document.querySelectorAll('iframe')).map(f => f.src || '').filter(Boolean).slice(0, 20)
})"""


_COOKIE_JS = r"""() => {
  // Click an "accept cookies" button if a consent banner is showing.
  const known = ['#onetrust-accept-btn-handler', '#accept-recommended-btn-handler',
    '#CybotCookiebotDialogBodyLevelButtonLevelOptinAllowAll', '#CybotCookiebotDialogBodyButtonAccept',
    '.cc-allow', '.cc-dismiss', '.cky-btn-accept', '#cookie_action_close_header', '.cmplz-accept',
    '#truste-consent-button', '.osano-cm-accept-all', '[data-testid="uc-accept-all-button"]',
    '#didomi-notice-agree-button', '.js-accept-cookies', '#hs-eu-confirmation-button'];
  const vis = el => !!(el && (el.offsetParent !== null || el.getClientRects().length));
  for (const sel of known) {
    try { const el = document.querySelector(sel); if (vis(el)) { el.click(); return 'accepted:' + sel; } } catch (e) {}
  }
  const re = /^(accept( all)?( cookies)?|allow( all)?( cookies)?|i accept|i agree|agree( and close)?|got it|ok(ay)?|accept & close|accept and continue|yes,? i agree)[.!]?$/i;
  const ctx = '[id*="cookie" i],[class*="cookie" i],[id*="consent" i],[class*="consent" i],' +
              '[id*="gdpr" i],[class*="gdpr" i],[aria-label*="cookie" i],[role="dialog"],[class*="banner" i]';
  for (const el of document.querySelectorAll('button,a,[role="button"],input[type="button"],input[type="submit"]')) {
    const t = ((el.innerText || el.value || el.getAttribute('aria-label') || '').trim()).replace(/\s+/g, ' ');
    if (!t || t.length > 40 || !re.test(t) || !vis(el)) continue;
    const box = el.closest(ctx);
    if (!box || !/cookie|consent|gdpr|privacy|tracking/i.test(box.innerText || '')) continue;
    el.click();
    return 'accepted:' + t;
  }
  return 'none';
}"""

_PAGER_JS = r"""([pageNo, jobHrefs]) => {
  // Find the control that loads more jobs. Marks it with data-sjh-pager and
  // returns {kind, text}; or {kind: 'none', why}.
  document.querySelectorAll('[data-sjh-pager]').forEach(e => e.removeAttribute('data-sjh-pager'));
  const vis = el => !!(el && (el.offsetParent !== null || el.getClientRects().length));
  const disabled = el => el.disabled || el.getAttribute('aria-disabled') === 'true' ||
      /(^|[\s_-])(disabled|inactive)([\s_-]|$)/i.test(el.className || '') ||
      !!(el.parentElement && /(^|[\s_-])disabled([\s_-]|$)/i.test(el.parentElement.className || ''));
  const skipCtx = '[class*="carousel" i],[class*="slick" i],[class*="swiper" i],[class*="slider" i],' +
      '[class*="testimonial" i],[class*="gallery" i],[class*="banner" i],header,footer nav[class*="menu" i],' +
      '[class*="faq" i],[id*="faq" i],[class*="accordion" i],[class*="review" i],[class*="blog" i],' +
      '[class*="news" i],[class*="press" i],[class*="event" i],[class*="award" i],[class*="story" i]';
  // When page 1's jobs came from links, a pager control must sit in the same
  // section as those links (within 6 ancestors), so FAQ "See more" buttons and
  // the like elsewhere on the page are never clicked.
  const hrefSet = new Set(jobHrefs || []);
  const jobEls = hrefSet.size ? Array.from(document.querySelectorAll('a[href]')).filter(a => hrefSet.has(a.href)) : [];
  const depthBelowBody = el => { let d = 0; for (let p = el; p && p !== document.body; p = p.parentElement) d++; return d; };
  const nearJobs = el => {
    if (!jobEls.length) return true;
    let p = el;
    for (let i = 0; i < 8 && p; i++, p = p.parentElement) {
      if (jobEls.some(j => p.contains(j))) {
        // Sharing only <body> with the job links counts as "near" only for a
        // control that sits near the top level of the page (simple layouts).
        if (p === document.body || p === document.documentElement) return depthBelowBody(el) <= 3;
        return true;
      }
    }
    return false;
  };
  const pagerCtx = '[class*="paginat" i],[class*="pager" i],[class*="paging" i],[aria-label*="pagination" i],' +
      '[aria-label*="pager" i],[class*="page-nav" i],[class*="pages" i],[role="navigation"]';
  const textOf = el => ((el.innerText || el.value || '').trim()).replace(/\s+/g, ' ');
  const labelOf = el => ((el.getAttribute('aria-label') || el.getAttribute('title') || '') + '').trim();
  const cands = Array.from(document.querySelectorAll(
      'a,button,[role="button"],[role="link"],input[type="button"],li[class*="next" i],span[class*="next" i],div[class*="next" i]'));
  const ok = el => vis(el) && !disabled(el) && !el.closest(skipCtx) && (!!el.closest(pagerCtx) || nearJobs(el));
  const linkOf = el => {
    const a = el.tagName === 'A' ? el : el.closest('a');
    const h = a ? (a.getAttribute('href') || '') : '';
    if (!h || h.startsWith('#') || /^javascript:/i.test(h)) return '';
    const abs = a.href;
    if (abs.split('#')[0] === location.href.split('#')[0]) return '';
    return abs;
  };
  const mark = (el, kind, text) => { el.setAttribute('data-sjh-pager', '1');
    return {kind, text: (text || '').slice(0, 60), href: linkOf(el)}; };

  // 1. Load more / show more
  const moreRe = /^(load|show|view|see|display)\s+more(\s+(jobs?|openings?|positions?|roles?|results?|opportunities|vacancies|listings?))?(\s*[(]\d+[)])?$|^more\s+(jobs?|openings?|positions?|roles?|results?)$/i;
  for (const el of cands) {
    const t = textOf(el) || labelOf(el);
    if (t && t.length < 60 && moreRe.test(t) && ok(el)) return mark(el, 'load_more', t);
  }
  // 2. Next / arrow
  const nextTextRe = /^(next|next page|next\s*[›»>→❯⟩]|[›»>→❯⟩]|>>|›|»)$/i;
  const nextLabelRe = /(^|\b)next(\b|$)|go to next page|next page/i;
  let disabledNext = false;
  for (const el of cands) {
    const t = textOf(el), lab = labelOf(el);
    const inPager = !!el.closest(pagerCtx);
    const relNext = (el.getAttribute('rel') || '').toLowerCase() === 'next';
    const cls = (el.className && el.className.baseVal !== undefined) ? el.className.baseVal : (el.className || '');
    const clsNext = /(^|[\s_-])next([\s_-]|$)/i.test(cls);
    const isNext = relNext || (t && t.length < 20 && nextTextRe.test(t)) || (lab && nextLabelRe.test(lab)) ||
                   (clsNext && (inPager || !t));
    if (!isNext) continue;
    if (/^[›»>→❯⟩]$|^>>$/.test(t) && !inPager && !lab) continue;   // bare arrow outside a pager: likely a carousel
    if (!vis(el) || el.closest(skipCtx) || (!inPager && !relNext && !nearJobs(el))) continue;
    if (disabled(el)) { disabledNext = true; continue; }
    let target = el;
    if (!/^(A|BUTTON|INPUT)$/.test(el.tagName) && !el.getAttribute('role')) {
      const inner = el.querySelector('a,button');
      if (inner) target = inner;
    }
    return mark(target, 'next', t || lab || 'arrow');
  }
  // 3. Numbered page: the link whose text is the next page number, inside a pager
  const want = String(pageNo + 1);
  for (const el of cands) {
    if (textOf(el) !== want) continue;
    if (!el.closest(pagerCtx) && !(el.parentElement && /^\d+$/.test(textOf(el.parentElement.previousElementSibling || {innerText: ''})))) continue;
    if (!ok(el)) continue;
    return mark(el, 'page_number', want);
  }
  return {kind: 'none', why: disabledNext ? 'next_disabled_last_page' : 'no_pager_found'};
}"""


async def _dismiss_cookie_banner(page) -> str:
    try:
        res = await page.evaluate(_COOKIE_JS)
        if res and res != "none":
            await page.wait_for_timeout(500)
        return res or "none"
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return f"error: {type(e).__name__}"


async def _click_pager(page, page_no: int, job_hrefs: Optional[list] = None) -> dict:
    """Finds and clicks the next pager control. Returns {kind, text} or {kind:'none', why}.
    A control that is a real link to another URL (often target=_blank, e.g.
    "View More Openings" -> the group careers portal) is opened in this tab
    with page.goto, because a click would open a tab we never read."""
    try:
        found = await page.evaluate(_PAGER_JS, [page_no, (job_hrefs or [])[:200]])
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return {"kind": "none", "why": f"pager_search_error: {type(e).__name__}"}
    if found.get("kind") == "none":
        return found
    if found.get("href"):
        try:
            await page.goto(found["href"], timeout=20_000, wait_until="domcontentloaded")
            found["click"] = "opened_link"
            return found
        except Exception as e:
            if is_dead_browser_error(e):
                raise ScraperBrowserDeadError(str(e)) from e
            return {"kind": "none", "why": f"open_link_failed: {type(e).__name__}"}
    loc = page.locator("[data-sjh-pager='1']").first
    try:
        await loc.scroll_into_view_if_needed(timeout=3000)
        await loc.click(timeout=4000)
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        # Overlay in the way or not "actionable": fall back to a DOM click.
        try:
            await page.evaluate("() => { const el = document.querySelector(\"[data-sjh-pager='1']\"); if (el) el.click(); }")
            found["click"] = "dom_click"
        except Exception as e2:
            if is_dead_browser_error(e2):
                raise ScraperBrowserDeadError(str(e2)) from e2
            return {"kind": "none", "why": f"click_failed: {type(e).__name__}"}
    return found


async def _paginate(page, jobs: list[dict], captured: list, pending: list, start_url: str,
                    diag: dict, partial: Optional[list]) -> list[dict]:
    """Clicks through Load more / Next / arrow / numbered pages, merging new jobs."""
    pg = {"pages_visited": 1, "clicks": [], "stopped": ""}
    diag["pagination"] = pg
    pg["cookie_banner"] = await _dismiss_cookie_banner(page)
    start_host = host_of(start_url)
    seen = {j.get("apply_url") for j in jobs}
    merged = list(jobs)
    anchor_hrefs = [j.get("apply_url") for j in jobs if j.get("apply_url")]
    on_platform = platform_for_url(start_url) is not None
    json_jobs_n = len(harvest_jobs_from_json(captured, start_url, on_platform=on_platform))
    deadline = time.monotonic() + PAGINATION_BUDGET_SECONDS
    page_no, stale = 1, 0
    for _ in range(PAGINATION_MAX_PAGES):
        if time.monotonic() > deadline:
            pg["stopped"] = f"time_budget_{PAGINATION_BUDGET_SECONDS}s"
            break
        url_before = page.url
        found = await _click_pager(page, page_no, anchor_hrefs)
        if found.get("kind") == "none":
            pg["stopped"] = found.get("why", "no_pager_found")
            break
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=PAGINATION_SETTLE_MS)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=PAGINATION_SETTLE_MS)
        except Exception:
            pass
        await page.wait_for_timeout(500)
        if (host_of(page.url) != start_host and platform_for_url(page.url) is None
                and not re.search(r"career|jobs?\b|recruit|talent|hiring|vacanc|opening", page.url, re.I)):
            pg["stopped"] = f"click_left_site:{page.url[:100]}"
            break
        anchors = await _collect_anchors(page)
        new = [j for j in filter_job_anchors(anchors, page.url) if j.get("apply_url") not in seen]
        for j in new:
            seen.add(j.get("apply_url"))
        merged.extend(new)
        if partial is not None:
            partial.extend(new)
        anchor_hrefs = [j.get("apply_url") for j in merged if j.get("apply_url")]
        await _drain_json(pending)
        # Progress = more *jobs* in the captured JSON, not just more responses
        # (Axis Bank's page fired analytics JSON on every click).
        new_json_n = len(harvest_jobs_from_json(captured, start_url, on_platform=on_platform))
        json_added = max(0, new_json_n - json_jobs_n)
        json_jobs_n = max(json_jobs_n, new_json_n)
        json_grew = json_added > 0
        if found["kind"] != "load_more":
            page_no += 1
        pg["pages_visited"] += 1
        pg["clicks"].append(f"{found['kind']}:{found.get('text', '')}"
                            + (f"({found['click']})" if found.get("click") else "")
                            + f" -> +{len(new)}" + (f" json+{json_added}" if json_grew else "")
                            + (" url_changed" if page.url != url_before else ""))
        if new or json_grew:
            stale = 0
        else:
            stale += 1
            if stale >= PAGINATION_STALE_LIMIT:
                pg["stopped"] = f"no_new_jobs_after_{stale}_clicks"
                break
    else:
        pg["stopped"] = f"page_limit_{PAGINATION_MAX_PAGES}"
    pg["jobs_added"] = len(merged) - len(jobs)
    pg["clicks"] = pg["clicks"][:20]
    return merged


async def _settle(page) -> None:
    """Wait for the page to finish its initial network activity (bounded)."""
    try:
        await page.wait_for_load_state("networkidle", timeout=NETWORKIDLE_WAIT_MS)
    except Exception:
        pass
    await page.wait_for_timeout(600)


async def _page_meta(page) -> dict:
    try:
        return await page.evaluate(_META_JS)
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        return {"title": "", "h1": "", "text": "", "anchors": 0, "iframes": []}


async def _collect_anchors(page) -> list[dict]:
    """Anchors from the main frame and child frames, one JS call per frame."""
    anchors: list[dict] = []
    for frame in page.frames[:MAX_FRAMES]:
        try:
            got = await frame.evaluate(_COLLECT_JS, [LISTING_SELECTORS, MAX_ANCHORS_PER_FRAME])
            for a in got:
                a["frame_url"] = frame.url
            anchors.extend(got)
        except Exception as e:
            if is_dead_browser_error(e):
                raise ScraperBrowserDeadError(str(e)) from e
            continue
    return anchors


# ─────────────────────────────────────────────────────────────────────────────
# Link filtering (pure)
# ─────────────────────────────────────────────────────────────────────────────

JOB_LINK_KEYWORDS = re.compile(
    r"(job|career|position|opening|role|apply|posting|opportunity|vacanc|recruit|requisition)",
    re.IGNORECASE,
)

NOISE_WORDS = re.compile(
    r"^(home|about|about us|contact|contact us|blog|news|press|team|product|pricing|sign|log|login|"
    r"privacy|terms|cookie|back|next|prev|previous|all jobs?|view all( jobs| openings| roles)?|see all|more|"
    r"careers?|apply( now| here)?|apply for (this )?job|learn more( and apply)?|"
    r"view (job|details|open roles?( now)?)|search( all)? jobs?|open positions?|"
    r"see (open )?(jobs?|roles?|positions?)|explore( all)? (jobs?|careers?|roles|opportunities)|"
    r"join (us|our team)|current openings?|"
    r"life at .{1,40}|our (culture|values|people|team|story|benefits)|culture|benefits|perks|faqs?|"
    r"students?|graduates?|early careers?|university( hiring)?|campus( hiring)?|events?|"
    r"diversity.{0,30}|why join us|why work (with|for) us|how we hire|hiring process|meet the team|"
    r"read more|know more|explore|details|view|submit( your)? (cv|resume)|drop your (cv|resume)|"
    r"refer a friend|employee login|job alerts?|talent community)[\s>›»→]*$",
    re.IGNORECASE,
)

# Link text that says nothing about the job itself — rescued only when the
# URL is clearly a job-detail URL.
GENERIC_LINK_TEXT = re.compile(
    r"^(apply( now| here| today)?|view( job| details| more| position)?|read more|know more|"
    r"learn more|details|more details|explore|see details|job details|view & apply|view and apply|"
    r"apply for (this )?(job|position|role)|click here|open|go|→|›|»)[\s>›»→]*$",
    re.IGNORECASE,
)

JOB_DETAIL_HREF = re.compile(
    r"(/(jobs?|careers?|openings?|positions?|vacanc[a-z]*|requisitions?|postings?|roles?|opportunit[a-z]*)"
    r"/(?!search|apply/?$|list|all/?$|page/)[^/?#]{3,}"
    r"|jobdetails?|job-details?|job_detail|jobdetail|/jd/|jobid=|job_id=|requisitionid=|reqid="
    r"|/j/[A-Za-z0-9]{4,}|/o/[^/?#]{3,}|/job/[^/?#]+)",
    re.IGNORECASE,
)

MAX_TITLE_WORDS = 8          # for links without a job-detail URL
MAX_TITLE_WORDS_DETAIL = 14  # job-detail URL: titles can be long ("Asst Manager - X - Y - City")


_ID_TAIL = re.compile(r"/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{4,}|[A-Za-z0-9]{2,}[-_]\d{3,}|[A-Z]{1,4}\d{3,}|R\d{4,})/?$", re.I)
_CARD_SEPARATORS = re.compile(r"\s+(?:·|•|\||—|–)\s+|\s+Location:\s+", re.I)
_ID_QUERY = re.compile(r"[?&](id|jobid|job_id|gh_jid|jid|posting_id|req|reqid|requisitionid)=[^&]{2,}", re.I)
_CARD_TAIL = re.compile(r"\s*(role details|view (job|details|role)|apply( now)?|learn more|read more|details)\s*[↗→›»>]*\s*$", re.I)


def is_job_detail_url(href: str) -> bool:
    """A URL that points at one specific job: the usual /jobs/<slug> shapes,
    or any multi-segment path on a hiring-platform host, or a path ending
    in a job id (uuid / long number / R12345)."""
    if JOB_DETAIL_HREF.search(href or ""):
        return True
    try:
        path = urlparse(href).path or ""
    except Exception:
        return False
    segs = [x for x in path.split("/") if x]
    if platform_for_url(href) and len(segs) >= 2:
        return True
    if _ID_QUERY.search(href or "") and JOB_LINK_KEYWORDS.search(path):
        return True   # /careers-job-application?id=74.96D
    if _ID_TAIL.search(path):
        host = host_of(href)
        return len(segs) >= 2 or host.startswith(("careers.", "jobs.", "career."))
    return False


def _first_line(text: str) -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _slug_title(href: str) -> str:
    """'…/jobs/senior-data-engineer-12345' -> 'Senior Data Engineer'. '' if
    the slug isn't wordy enough to be a title."""
    try:
        path = unquote(urlparse(href).path).rstrip("/")
    except Exception:
        return ""
    seg = path.rsplit("/", 1)[-1]
    seg = re.sub(r"\.(html?|aspx|php)$", "", seg, flags=re.I)
    words = [w for w in re.split(r"[-_+\s]+", seg) if w]
    words = [w for w in words if not re.fullmatch(r"[0-9a-f]{6,}|\d+|[A-Z]{1,3}\d+", w, flags=re.I)]
    alpha = [w for w in words if re.search(r"[A-Za-z]{2,}", w)]
    if len(alpha) < 2:
        return ""
    return " ".join(w if w.isupper() else w.capitalize() for w in words)[:150]


def choose_title(text: str, card: str, aria: str, href: str) -> tuple[str, bool]:
    """Best human title for a link. Returns (title, rescued) where `rescued`
    means the link's own text was generic/whole-card and the title came
    from somewhere else — such links must have a job-detail URL."""
    text = (text or "").strip()
    card = (card or "").strip()
    first = _first_line(text)
    one_line_text = re.sub(r"\s+", " ", text)

    if not text or GENERIC_LINK_TEXT.match(first) or GENERIC_LINK_TEXT.match(one_line_text):
        for cand in (card, aria, _slug_title(href)):
            cand = _first_line(cand)
            if cand and not GENERIC_LINK_TEXT.match(cand) and not NOISE_WORDS.match(cand):
                return cand, True
        return first, False

    multi = "\n" in text or len(one_line_text.split()) > MAX_TITLE_WORDS
    if multi and "\n" not in text:
        # One-line card text: "Data Engineer Remote US · Remote India Role Details ↗"
        head = _CARD_TAIL.sub("", one_line_text)
        head = _CARD_SEPARATORS.split(head)[0].strip()
        if card and _first_line(card) and len(_first_line(card).split()) <= MAX_TITLE_WORDS_DETAIL:
            return _first_line(card), True
        if head and head != one_line_text and 2 <= len(head.split()) <= MAX_TITLE_WORDS_DETAIL:
            return head, True
    if multi:
        # Whole job card inside the link: prefer the card heading, else the first line.
        if card and _first_line(card) and len(_first_line(card).split()) <= MAX_TITLE_WORDS_DETAIL:
            return _first_line(card), True
        if first and 5 <= len(first) <= 150 and len(first.split()) <= MAX_TITLE_WORDS_DETAIL:
            return first, first != one_line_text
    return one_line_text, False


def _job_link_reject_reason(href: str, text: str, detail_url: Optional[bool] = None) -> Optional[str]:
    """None if the link looks like a job link, else a short reason code."""
    stripped = (text or "").strip()
    if detail_url is None:
        detail_url = is_job_detail_url(href or "")
    if NOISE_WORDS.match(stripped):
        return "noise_word"
    if len(stripped) < 5 or len(stripped) > 150:
        return "title_length"
    if len(stripped.split()) > (MAX_TITLE_WORDS_DETAIL if detail_url else MAX_TITLE_WORDS):
        return "too_many_words"
    if not (JOB_LINK_KEYWORDS.search(href or "") or JOB_LINK_KEYWORDS.search(stripped)):
        return "no_job_keyword"
    return None


def _looks_like_job_link(href: str, text: str) -> bool:
    return _job_link_reject_reason(href, text) is None


def _clean_title(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"[\s>»›→]+$", "", cleaned).strip()


def filter_job_anchors(anchors: list[dict], page_url: str, diag: Optional[dict] = None) -> list[dict]:
    """Turn collected anchors into job dicts. Pure (no browser).

    Anchors are grouped by the first LISTING_SELECTORS entry they match
    (sel index, -1 = none); each group and the full set are filtered, and
    the group yielding the most jobs wins."""
    page_base = (page_url or "").split("#")[0].rstrip("/")

    def run(cands):
        jobs, seen = [], set()
        rc: dict[str, int] = {}
        samples: list[str] = []
        empty = 0
        for a in cands:
            href = (a.get("href") or "").strip()
            raw = a.get("text") or ""
            if not href or href.lower().startswith(("mailto:", "tel:", "javascript:", "data:")):
                continue
            if not raw.strip() and not (a.get("card") or a.get("aria")):
                empty += 1
                continue
            hbase = href.split("#")[0].rstrip("/")
            if hbase == page_base or not hbase:
                reason = "same_page"
            elif host_matches(host_of(href), NON_CAREERS_HOSTS):
                reason = "social_or_board_host"
            else:
                reason = None
            title, rescued = choose_title(raw, a.get("card", ""), a.get("aria", ""), href)
            detail = is_job_detail_url(href)
            if reason is None:
                reason = _job_link_reject_reason(href, title, detail_url=detail)
            if reason is None and rescued and not detail:
                reason = "generic_text_not_detail_url"
            if reason:
                rc[reason] = rc.get(reason, 0) + 1
                if len(samples) < 6:
                    raw_compact = re.sub(r'\s+', ' ', raw)[:50]   # py3.11: no backslash inside f-string
                    samples.append(f"[{reason}] {raw_compact!r} -> {href[:80]}")
                continue
            if hbase in seen:
                continue
            seen.add(hbase)
            jobs.append({
                "title": _clean_title(title), "department": "", "location": "",
                "apply_url": href, "posted_at": "", "description_snippet": "",
            })
        return jobs, rc, samples, empty

    groups: dict[int, list[dict]] = {}
    for a in anchors:
        groups.setdefault(a.get("sel", -1), []).append(a)
    options = [("a[href] (all)", anchors)] + [
        (LISTING_SELECTORS[i], g) for i, g in sorted(groups.items()) if i >= 0]

    best = None
    for label, cands in options:
        res = run(cands)
        if best is None or len(res[0]) > len(best[1][0]):
            best = (label, res)
    label, (jobs, rc, samples, empty) = best
    if diag is not None:
        diag["listing_selector"] = label
        diag["candidate_links"] = len(anchors)
        diag["kept_links"] = len(jobs)
        diag["reject_counts"] = rc
        diag["reject_samples"] = samples
        diag["empty_text_links"] = empty
    return jobs


# Back-compat shim for anything calling the old helper with a live page.
async def _extract_links(page, careers_url: str, base_domain: str,
                         diag: Optional[dict] = None) -> list[dict]:
    return filter_job_anchors(await _collect_anchors(page), page.url or careers_url, diag)


# ─────────────────────────────────────────────────────────────────────────────
# Job descriptions
# ─────────────────────────────────────────────────────────────────────────────

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
    """Fetch description snippets for (up to MAX_DESCRIPTION_FETCHES of) the
    jobs that still lack one and have a real per-job page."""
    todo = [j for j in jobs
            if j.get("apply_url") and "#job-" not in j["apply_url"]
            and len(j.get("description_snippet") or "") < 100][:MAX_DESCRIPTION_FETCHES]
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


# ─────────────────────────────────────────────────────────────────────────────
# Main scrape
# ─────────────────────────────────────────────────────────────────────────────

async def _read_json(resp, sink: list) -> None:
    try:
        data = await asyncio.wait_for(resp.json(), timeout=5)
        sink.append((resp.url, data))
    except Exception:
        pass


def _attach_json_capture(page, captured: list, pending: list) -> None:
    def on_response(resp):
        try:
            if len(pending) >= MAX_JSON_RESPONSES:
                return
            if resp.request.resource_type not in ("xhr", "fetch"):
                return
            ct = (resp.headers.get("content-type") or "").lower()
            if "json" not in ct:
                return
            cl = resp.headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > MAX_JSON_BYTES:
                return
            if resp.status != 200:
                return
            pending.append(asyncio.ensure_future(_read_json(resp, captured)))
        except Exception:
            pass
    page.on("response", on_response)


async def _drain_json(pending: list, timeout: float = 3.0) -> None:
    if not pending:
        return
    done, not_done = await asyncio.wait(list(pending), timeout=timeout)
    for t in not_done:
        t.cancel()


def _platform_urls(final_url: str, frame_urls: list[str], anchors: list[dict]) -> list[str]:
    """Hiring-platform URLs this page points at, best first: the page
    itself (after redirects), its iframes, then outbound links."""
    out: list[str] = []
    final_host = host_of(final_url)

    def add(u):
        if u and u.startswith("http") and platform_for_url(u) and u not in out:
            out.append(u)

    add(final_url)
    for u in frame_urls:
        add(u)
    for a in anchors:
        u = a.get("href") or ""
        if host_of(u) != final_host:
            add(u)
        if len(out) >= 6:
            break
    return out


async def _scrape_in_context(
    ctx, careers_url: str, base_domain: str, fetch_descriptions: bool = True,
    diag: Optional[dict] = None, partial: Optional[list] = None, company_host: str = "",
) -> list[dict]:
    """Opens the page, navigates, validates, extracts jobs. Raises
    ScraperBrowserDeadError if the browser itself has died; ordinary
    per-page failures are recorded in diag and return []."""
    from playwright.async_api import TimeoutError as PWTimeout
    if diag is None:
        diag = {}

    try:
        page = await ctx.new_page()
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        print(f"[async_career_scraper] Could not open a page for {careers_url}: {e}")
        return []

    captured: list = []
    pending: list = []
    _attach_json_capture(page, captured, pending)
    page.set_default_timeout(15_000)
    try:
        diag["stage_reached"] = "goto"
        resp = await page.goto(careers_url, timeout=20_000, wait_until="domcontentloaded")
        await _settle(page)
        meta = await _page_meta(page)
        if meta.get("anchors", 0) < 5 and len(meta.get("text", "")) < 300:
            # Still a JS shell — give the app one more chance to render.
            await page.wait_for_timeout(EMPTY_SHELL_EXTRA_WAIT_MS)
            meta = await _page_meta(page)

        final_url = page.url or careers_url
        diag["final_url"] = final_url[:300]
        status = resp.status if resp is not None else None
        ctype = (resp.headers.get("content-type", "") if resp is not None else "")
        reason = classify_page(careers_url, final_url, status, ctype, meta.get("title", ""),
                               meta.get("h1", ""), meta.get("text", ""),
                               company_host=company_host or host_of(careers_url),
                               require_career_words=True)
        if reason:
            diag["outcome"] = "invalid_page"
            diag["page_invalid"] = reason
            return []

        diag["stage_reached"] = "extract_links"
        anchors = await _collect_anchors(page)
        frame_urls = [f.url for f in page.frames[1:MAX_FRAMES] if f.url and f.url != "about:blank"]
        frame_urls += [u for u in meta.get("iframes", []) if u not in frame_urls]
        diag["frames"] = len(page.frames)
        plats = _platform_urls(final_url, frame_urls, anchors)
        if plats:
            diag["platform_urls"] = plats

        # Does this careers page embed / point at an API-capable ATS?
        embedded = False
        try:
            emb = _extract_ats_from_html(await page.content(), final_url)
            hit = (emb.ats, emb.token) if (emb and emb.can_api and emb.token) else None
            if not hit:
                for u in [final_url] + frame_urls + plats:
                    h = parse_ats_url(u)
                    if h and h[0] in API_ATS:
                        hit = h
                        break
            if hit:
                diag["embedded_ats"] = hit
                embedded = True
        except Exception as e:
            if is_dead_browser_error(e):
                raise ScraperBrowserDeadError(str(e)) from e

        jobs = filter_job_anchors(anchors, final_url, diag=diag)
        if partial is not None:
            partial.extend(jobs)

        # Pagination: only on a page that is already a job listing (page 1
        # produced job links or job JSON), so we never click "Next" on a blog.
        await _drain_json(pending)
        first_json = harvest_jobs_from_json(captured, final_url,
                                            on_platform=platform_for_url(final_url) is not None)
        if (jobs or first_json) and not embedded:
            diag["stage_reached"] = "pagination"
            jobs = await _paginate(page, jobs, captured, pending, final_url, diag, partial)
        else:
            diag["pagination"] = {"skipped": "embedded_ats_board" if embedded else "no_jobs_on_first_page"}

        await _drain_json(pending)
        json_jobs = harvest_jobs_from_json(captured, final_url,
                                           on_platform=platform_for_url(final_url) is not None)
        diag["json_responses"] = len(captured)
        diag["json_jobs_found"] = len(json_jobs)
        if len(json_jobs) > len(jobs):
            jobs = json_jobs
            diag["used_json_capture"] = True
            if partial is not None:
                partial.clear()
                partial.extend(jobs)

        diag["stage_reached"] = "job_descriptions"
        diag["links_before_descriptions"] = len(jobs)
        if fetch_descriptions and not embedded:
            await _fill_descriptions(ctx, jobs)
        return jobs
    except PWTimeout:
        print(f"[async_career_scraper] Timeout loading {careers_url}")
        diag["outcome"] = "goto_timeout"
        return []
    except ScraperBrowserDeadError:
        raise
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        raise
    finally:
        for t in pending:
            if not t.done():
                t.cancel()
        try:
            await page.close()
        except Exception:
            pass


async def _scrape_with_browser(
    browser, careers_url: str, base_domain: str, fetch_descriptions: bool = True,
    diag: Optional[dict] = None, company_host: str = "",
) -> list[dict]:
    """Scrape a careers page with hard timeout protection."""
    jobs = []
    partial: list[dict] = []   # jobs found so far; survives a hard timeout
    if diag is None:
        diag = {}

    try:
        ctx = await new_context(browser)
    except Exception as e:
        if is_dead_browser_error(e):
            raise ScraperBrowserDeadError(str(e)) from e
        print(f"[async_career_scraper] Could not open a browser context for {careers_url}: {e}")
        diag["outcome"] = "context_error"
        return jobs

    try:
        try:
            async with asyncio.timeout(HARD_TIMEOUT_SECONDS):
                jobs = await _scrape_in_context(
                    ctx, careers_url, base_domain, fetch_descriptions=fetch_descriptions,
                    diag=diag, partial=partial, company_host=company_host,
                )
        except AttributeError:
            # asyncio.timeout() is Python 3.11+; fall back to wait_for on older runtimes.
            jobs = await asyncio.wait_for(
                _scrape_in_context(
                    ctx, careers_url, base_domain, fetch_descriptions=fetch_descriptions,
                    diag=diag, partial=partial, company_host=company_host,
                ),
                timeout=HARD_TIMEOUT_SECONDS,
            )
        diag.setdefault("outcome", "ok")
    except ScraperBrowserDeadError:
        raise
    except (asyncio.TimeoutError, TimeoutError):
        print(f"[async_career_scraper] Hard timeout (>{HARD_TIMEOUT_SECONDS}s) on {careers_url}")
        if partial:
            jobs = list(partial)
            print(f"[async_career_scraper] Kept {len(jobs)} link(s) found before the timeout on {careers_url}")
        diag["outcome"] = "hard_timeout"
        diag["partial_jobs_kept"] = len(jobs)
    except Exception as e:
        msg = str(e)
        print(f"[async_career_scraper] Error scraping {careers_url}: {msg[:300]}")
        if "ERR_HTTP2_PROTOCOL_ERROR" in msg:
            diag["outcome"] = "http2_error"
        elif "ERR_NAME_NOT_RESOLVED" in msg or "ERR_CONNECTION_REFUSED" in msg:
            diag["outcome"] = "error: site_unreachable " + msg[:120]
        elif "ERR_CERT" in msg or "ERR_SSL" in msg:
            diag["outcome"] = "error: ssl " + msg[:120]
        else:
            diag["outcome"] = f"error: {msg}"[:200]
    finally:
        try:
            await ctx.close()
        except Exception:
            pass

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Careers-page discovery (real browser)
#
# detect_ats() only ever looks for a careers page with plain `requests`
# calls. Sites that block non-browser clients, need JS, or keep careers under
# an unusual URL end up with no careers URL at all. This loads the homepage
# in the real browser and picks the best careers link from its anchors
# (including iframes and hover/click nav dropdowns).
# ─────────────────────────────────────────────────────────────────────────────

_ANCHOR_JS = """els => els.map(e => ({
    href: e.href || '',
    text: ((e.innerText || e.textContent || '').trim()).slice(0, 80),
    aria: (e.getAttribute('aria-label') || e.getAttribute('title') || '').slice(0, 80)
}))"""

_CAREER_LINK_TEXT = re.compile(
    r"^\s*(careers?|jobs?|join( us| our team| the team| our family)?|work (with|at|for) us|"
    r"open (positions|roles)|current (openings?|opportunities|vacanc(y|ies))|we'?re hiring|opportunities|"
    r"employment|explore careers|view (all )?jobs|search jobs|life at .{1,30}|"
    r"career opportunities|careers? (at|with) .{1,30}|people (&|and) culture|drive your career|"
    r"recruitments?|hr (&|and) careers?|vacanc(y|ies)|job openings?|"
    r"कैरियर|करियर|नौकरी|वर्तमान नौकरी|भर्ती|रिक्तियां)\s*[>›»]?\s*$",
    re.IGNORECASE,
)
_CAREER_TEXT_HINT = re.compile(r"career|job|hiring|join|openings|recruit|vacanc|कैरियर|करियर|नौकरी|भर्ती",
                               re.IGNORECASE)
_CAREER_HREF = re.compile(
    r"/(careers?|jobs?|join(-us|-our-family|-our-team)?|work-(with|at|for)-us|employment|opportunities|"
    r"openings|open-positions|recruitments?|vacanc(y|ies)|current-opportunities|current-openings|"
    r"life-at[a-z0-9-]*|our-people|latest-job-opening)(/|$|\?|-|\.html?|\.page|\.aspx|\.php)",
    re.IGNORECASE,
)
_BAD_LINK_HOSTS = NON_CAREERS_HOSTS
_NON_HTML_LINK = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|docx?|zip)(\?|$)", re.I)

NAV_TRIGGER_TEXT = re.compile(
    r"^\s*(company|about( us)?|who we are|our company|resources|product s?|"
    r"solutions?|platform|services|more|team|people|investors?|corporate)\s*[▾▼⌄▾▼]?\s*$",
    re.IGNORECASE,
)
MAX_DROPDOWN_TRIGGERS = 8
DROPDOWN_SCAN_BUDGET_SECONDS = 8
NAV_TRIGGER_SELECTOR = (
    "header a, header button, header [role='button'], header li, "
    "nav a, nav button, nav [role='button'], nav li, "
    "[class*='navbar'] a, [class*='navbar'] button, [class*='navbar'] li"
)


def _host_matches(host: str, domains) -> bool:
    return host_matches(host, domains)


async def _open_dropdowns_and_collect_anchors(page, existing_anchors: list[dict]) -> list[dict]:
    """Hover, then click, likely nav-dropdown triggers (Company/About/
    Resources/...) and re-scan a[href] after each, to catch careers links
    that only render once the menu is open. Best-effort."""
    all_anchors = list(existing_anchors)
    try:
        triggers = page.locator(NAV_TRIGGER_SELECTOR)
        count = await triggers.count()
    except Exception:
        return all_anchors

    base_url = page.url
    scan_deadline = time.monotonic() + DROPDOWN_SCAN_BUDGET_SECONDS
    tried = 0
    for i in range(min(count, 40)):
        if tried >= MAX_DROPDOWN_TRIGGERS or time.monotonic() >= scan_deadline:
            break
        try:
            el = triggers.nth(i)
            text = (await el.inner_text(timeout=1000) or "").strip()
        except Exception:
            continue
        if not NAV_TRIGGER_TEXT.match(text):
            continue
        tried += 1

        try:
            await el.hover(timeout=1200)
            await page.wait_for_timeout(400)
            all_anchors.extend(await page.eval_on_selector_all("a[href]", _ANCHOR_JS))
        except Exception:
            pass

        if time.monotonic() >= scan_deadline:
            break

        try:
            href = await el.get_attribute("href", timeout=1000)
        except Exception:
            href = None
        safe_to_click = (
            not href or href.strip() in ("", "#") or href.strip().lower().startswith("javascript:")
        )

        if safe_to_click:
            try:
                await el.click(timeout=1200)
                await page.wait_for_timeout(400)
                if page.url != base_url:
                    await page.go_back(timeout=3000)
                    await page.wait_for_timeout(300)
                else:
                    all_anchors.extend(await page.eval_on_selector_all("a[href]", _ANCHOR_JS))
            except Exception:
                pass

        try:
            await page.keyboard.press("Escape")
            await page.mouse.move(0, 0)
            await page.wait_for_timeout(150)
        except Exception:
            pass

    return all_anchors


def _pick_careers_link(anchors: list[dict], page_url: str) -> Optional[str]:
    """Choose the most likely careers link from a homepage's anchors, or None.
    Pure function (no browser) so it can be unit-tested."""
    page_base = (page_url or "").split("#")[0]
    best, best_score = None, 0
    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href.startswith("http") or href.split("#")[0] == page_base:
            continue
        if _NON_HTML_LINK.search(href):
            continue   # Careers.jpg / careers.webp / a PDF is not a careers page
        parsed = urlparse(href)
        host = (parsed.hostname or "").lower()
        if host_matches(host, _BAD_LINK_HOSTS):
            continue
        text = re.sub(r"\s+", " ", (a.get("text") or a.get("aria") or "")).strip()

        score = 0
        if _CAREER_LINK_TEXT.match(text):
            score += 3
        if platform_for_url(href):
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

    `diag` (diagnostics only) gets `outcome`: found | homepage_is_platform |
    no_careers_link_on_homepage | homepage_invalid:<reason> |
    homepage_load_failed: ... | no_website | http2_error | error: ...
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
            ctx = await new_context(browser)
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
                resp = await page.goto(base_url, timeout=20_000, wait_until="domcontentloaded")
                try:
                    await page.wait_for_load_state("networkidle", timeout=4000)
                except Exception:
                    pass
                final = page.url or base_url
                if platform_for_url(final):
                    diag["outcome"] = "homepage_is_platform"
                    return final
                meta = await _page_meta(page)
                bad = classify_page(base_url, final, resp.status if resp else None,
                                    resp.headers.get("content-type", "") if resp else "",
                                    meta.get("title", ""), meta.get("h1", ""), meta.get("text", ""),
                                    require_career_words=False)
                if bad in ("parked_domain", "bot_wall", "not_html") or (bad or "").startswith("http_"):
                    diag["outcome"] = f"homepage_invalid:{bad}"
                    return None

                anchors = []
                for frame in page.frames[:MAX_FRAMES]:
                    try:
                        anchors.extend(await frame.eval_on_selector_all("a[href]", _ANCHOR_JS))
                    except Exception:
                        continue
                diag["anchors_seen"] = len(anchors)
                best = _pick_careers_link(anchors, final)

                if not best:
                    anchors = await _open_dropdowns_and_collect_anchors(page, anchors)
                    diag["anchors_seen_after_dropdown_scan"] = len(anchors)
                    best = _pick_careers_link(anchors, page.url)

                diag["outcome"] = "found" if best else "no_careers_link_on_homepage"
                return best
            except ScraperBrowserDeadError:
                raise
            except Exception as e:
                if is_dead_browser_error(e):
                    raise ScraperBrowserDeadError(str(e)) from e
                if "ERR_HTTP2_PROTOCOL_ERROR" in str(e):
                    diag["outcome"] = "http2_error"
                else:
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
