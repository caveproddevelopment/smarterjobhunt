"""
ATS API — fetches job listings from the public JSON APIs of hiring platforms.

Each function returns a list of dicts with normalized keys:
  {
    "title":                 str,
    "department":            str,
    "location":              str,
    "apply_url":             str,   # unique per job (it is the dedup key downstream)
    "posted_at":             str,   # ISO date string or empty
    "description_snippet":   str,   # first N chars of cleaned JD text, see text_extract.py
  }

Supported (token formats are produced by platforms.parse_ats_url):
  greenhouse / greenhouse_eu   board slug
  lever / lever_eu             company slug
  ashby                        board name (case-sensitive, may be URL-encoded)
  workable                     account slug
  smartrecruiters              company identifier
  workday                      "<host>|<tenant>|<site>"
  oracle                       "<host>|<siteNumber>"  (siteNumber may be "")
  recruitee                    subdomain
  phenom                       "<host>|<base path>"  e.g. "careers.adobe.com|us/en"

Description snippets matter beyond search: the backend's auto-clean
(routes/staging.py) only auto-approves a staged row with >= 100 chars of
raw_text.

2026-10-15 — descriptions moved out of the nightly scrape:
  - The nightly scrape (fetch_jobs with the default fetch_details=False)
    no longer makes per-job detail calls. Descriptions that come free in
    the list response are still kept (Greenhouse, Lever, Ashby, Recruitee,
    and Oracle's short description).
  - Per-job descriptions are fetched afterwards by
    run_description_backfill.py, only for jobs not already in production,
    using the detail_* functions at the bottom of this module (they work
    from the apply_url stored in jobs_staging).
  - MAX_JOBS_PER_COMPANY raised from 1,000 to 5,000. List paging is also
    bounded by LIST_BUDGET_SECONDS so a very large board returns what it
    has instead of hitting the orchestrator's per-fetch timeout and
    returning nothing.

2026-10-13 changes:
  - Ashby: the public posting API returns "jobs" with title/department/
    location/publishedAt/jobUrl. The old code read "jobPostings",
    "departmentName", "locationName", "publishedDate" (fields from a
    different, private API), so every Ashby board came back empty —
    confirmed against jobs.ashbyhq.com/bolna (5 live jobs). Board names are
    now URL-quoted properly (spaces/dots).
  - Added greenhouse_eu, lever_eu, smartrecruiters, workday, oracle,
    recruitee adapters.
  - Workable: falls back to the v1 widget endpoint when v3 fails or is empty.
"""

import re
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Optional
from urllib.parse import quote, unquote

from .text_extract import make_snippet

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

DETAIL_FETCH_CAP = 60        # max per-job detail requests per company (only when fetch_details=True)
DETAIL_CONCURRENCY = 5
MAX_JOBS_PER_COMPANY = 5000  # pagination safety cap (was 1000 until 2026-10-15)
LIST_BUDGET_SECONDS = 120    # stop paging after this long and keep what we have
# Phenom boards get their own cap (2026-11-11): Advance Auto has ~16,300 jobs and
# TJX ~10,000, and the Phenom handler fetches all 16,284 of Advance Auto's in
# ~70s, inside LIST_BUDGET_SECONDS. If a board is slower, paging still stops at
# the budget and keeps what it has (diag "truncated").
PHENOM_MAX_JOBS = 25000

# Set per call by fetch_jobs(); read by the paging loops. Thread-local so
# concurrent fetches (asyncio.to_thread) don't share one deadline/diag.
import threading
_CALL = threading.local()


def _paging_expired() -> bool:
    deadline = getattr(_CALL, "deadline", None)
    if deadline is not None and time.monotonic() >= deadline:
        d = getattr(_CALL, "diag", None)
        if d is not None:
            d["truncated"] = f"list paging stopped after {LIST_BUDGET_SECONDS}s"
        return True
    return False


def _job_cap(ats: str) -> int:
    return PHENOM_MAX_JOBS if ats == "phenom" else MAX_JOBS_PER_COMPANY


def _note_cap(n: int, cap: int = MAX_JOBS_PER_COMPANY) -> None:
    d = getattr(_CALL, "diag", None)
    if d is not None and n >= cap:
        name = "PHENOM_MAX_JOBS" if cap == PHENOM_MAX_JOBS else "MAX_JOBS_PER_COMPANY"
        d["truncated"] = f"hit {name}={cap}"


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def fetch_jobs(ats: str, token: str, fetch_descriptions: bool = True,
               diag: Optional[dict] = None, fetch_details: bool = False) -> list[dict]:
    """Fetch all open jobs from the given ATS. Never raises: errors are
    printed, recorded in `diag` (fetch_status / fetch_error), and [] returned.

    fetch_descriptions: keep descriptions the list response already carries.
    fetch_details: also make one detail request per job (capped at
    DETAIL_FETCH_CAP) for platforms whose list has no description. Off by
    default since 2026-10-15; run_description_backfill.py does this instead,
    only for jobs not already in production."""
    fn = {
        "greenhouse":      lambda t, fd, dt: _fetch_greenhouse(t, fd, eu=False),
        "greenhouse_eu":   lambda t, fd, dt: _fetch_greenhouse(t, fd, eu=True),
        "lever":           lambda t, fd, dt: _fetch_lever(t, fd, eu=False),
        "lever_eu":        lambda t, fd, dt: _fetch_lever(t, fd, eu=True),
        "ashby":           lambda t, fd, dt: _fetch_ashby(t, fd),
        "workable":        _fetch_workable,
        "smartrecruiters": _fetch_smartrecruiters,
        "workday":         _fetch_workday,
        "oracle":          _fetch_oracle,
        "recruitee":       lambda t, fd, dt: _fetch_recruitee(t, fd),
        "phenom":          _fetch_phenom,
    }.get(ats)

    if fn is None:
        if diag is not None:
            diag["fetch_error"] = f"unsupported ats: {ats}"
        return []

    _CALL.deadline = time.monotonic() + LIST_BUDGET_SECONDS
    _CALL.diag = diag
    try:
        jobs = fn(token, fetch_descriptions, fetch_descriptions and fetch_details)
        cap = _job_cap(ats)
        _note_cap(len(jobs), cap)
        return jobs[:cap]
    except Exception as e:
        print(f"[ats_api] Error fetching from {ats}/{token}: {e}")
        if diag is not None:
            resp = getattr(e, "response", None)
            diag["fetch_status"] = getattr(resp, "status_code", None)
            diag["fetch_error"] = f"{type(e).__name__}: {e}"[:200]
        return []
    finally:
        _CALL.deadline = None
        _CALL.diag = None


def _map_details(fn, items: list, cap: int = DETAIL_FETCH_CAP) -> list:
    """Run fn(item) for the first `cap` items, DETAIL_CONCURRENCY at a time;
    returns results in order ("" for items past the cap or on error)."""
    head = items[:cap]
    out = [""] * len(items)
    if not head:
        return out

    def safe(x):
        try:
            return fn(x) or ""
        except Exception:
            return ""

    with ThreadPoolExecutor(max_workers=DETAIL_CONCURRENCY) as ex:
        for i, res in enumerate(ex.map(safe, head)):
            out[i] = res
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_greenhouse(token: str, fetch_descriptions: bool = True, eu: bool = False) -> list[dict]:
    host = "boards-api.eu.greenhouse.io" if eu else "boards-api.greenhouse.io"
    url = f"https://{host}/v1/boards/{token}/jobs?content=true"
    r = requests.get(url, headers=HEADERS, timeout=15)
    if eu and r.status_code == 404:
        # Not every EU board is served from the EU API host; try the main one.
        r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                         headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data.get("jobs", []):
        dept = ""
        if j.get("departments"):
            dept = j["departments"][0].get("name", "")
        loc = ""
        if j.get("offices"):
            loc = j["offices"][0].get("name", "")
        elif j.get("location"):
            loc = j["location"].get("name", "")
        jobs.append({
            "title":               j.get("title", ""),
            "department":          dept,
            "location":            loc,
            "apply_url":           j.get("absolute_url", ""),
            "posted_at":           _parse_ts(j.get("first_published") or j.get("updated_at", "")),
            "description_snippet": make_snippet(j.get("content", ""), is_html=True) if fetch_descriptions else "",
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Lever
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_lever(token: str, fetch_descriptions: bool = True, eu: bool = False) -> list[dict]:
    host = "api.eu.lever.co" if eu else "api.lever.co"
    url = f"https://{host}/v0/postings/{token}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data:
        cats = j.get("categories", {}) or {}
        apply_url = j.get("hostedUrl") or j.get("applyUrl", "")
        snippet = ""
        if fetch_descriptions:
            if j.get("descriptionPlain"):
                snippet = make_snippet(j.get("descriptionPlain", ""), is_html=False)
            else:
                snippet = make_snippet(j.get("description", ""), is_html=True)
        jobs.append({
            "title":               j.get("text", ""),
            "department":          cats.get("department", cats.get("team", "")),
            "location":            cats.get("location", cats.get("allLocations", [""])[0] if cats.get("allLocations") else ""),
            "apply_url":           apply_url,
            "posted_at":           _parse_ts_ms(j.get("createdAt", 0)),
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Ashby
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_ashby(token: str, fetch_descriptions: bool = True) -> list[dict]:
    # Verified 2026-10-13 against jobs.ashbyhq.com/bolna: top-level "jobs",
    # each with title, department, team, location, isListed, isRemote,
    # publishedAt, jobUrl, applyUrl, descriptionHtml, descriptionPlain.
    board = quote(unquote(token), safe="")
    url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    postings = data.get("jobs")
    if postings is None:
        postings = data.get("jobPostings", [])   # legacy shape, just in case

    jobs = []
    for j in postings or []:
        if j.get("isListed") is False:
            continue
        loc = j.get("location") or j.get("locationName") or ""
        if isinstance(loc, dict):
            loc = loc.get("name", "")
        if not loc and j.get("isRemote"):
            loc = "Remote"
        snippet = ""
        if fetch_descriptions:
            if j.get("descriptionPlain"):
                snippet = make_snippet(j["descriptionPlain"], is_html=False)
            else:
                snippet = make_snippet(j.get("descriptionHtml", ""), is_html=True)
        jobs.append({
            "title":               j.get("title", ""),
            "department":          j.get("department") or j.get("departmentName") or j.get("team") or "",
            "location":            loc,
            "apply_url":           j.get("jobUrl") or j.get("applyUrl") or "",
            "posted_at":           _parse_ts(j.get("publishedAt") or j.get("publishedDate") or ""),
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Workable
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_workable(token: str, fetch_descriptions: bool = True, fetch_details: bool = False) -> list[dict]:
    """v3 search endpoint first (what apply.workable.com itself uses), then
    the v1 widget endpoint if v3 errors or returns nothing."""
    v3_error = None
    try:
        jobs = _fetch_workable_v3(token, fetch_details)
        if jobs:
            return jobs
    except Exception as e:
        v3_error = e
    try:
        jobs = _fetch_workable_widget(token, fetch_details)
    except Exception:
        if v3_error is not None:
            raise v3_error
        raise
    return jobs


def _fetch_workable_v3(token: str, fetch_details: bool) -> list[dict]:
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
    body = {"query": "", "location": [], "department": [], "worktype": [], "remote": []}
    results, next_page = [], None
    while len(results) < MAX_JOBS_PER_COMPANY:
        payload = dict(body, token=next_page) if next_page else body
        r = requests.post(url, json=payload, headers={**HEADERS, "Content-Type": "application/json"}, timeout=15)
        r.raise_for_status()
        data = r.json()
        results.extend(data.get("results", []) or [])
        next_page = data.get("nextPage")
        if not next_page or _paging_expired():
            break

    snippets = (_map_details(lambda j: detail_workable(token, j.get("shortcode", "")), results)
                if fetch_details else [""] * len(results))
    jobs = []
    for j, snippet in zip(results, snippets):
        shortcode = j.get("shortcode", "")
        loc = j.get("location")
        jobs.append({
            "title":               j.get("title", ""),
            "department":          j.get("department", "") if isinstance(j.get("department"), str) else "",
            "location":            ", ".join(x for x in [loc.get("city", ""), loc.get("country", "")] if x) if isinstance(loc, dict) else "",
            "apply_url":           f"https://apply.workable.com/{token}/j/{shortcode}/",
            "posted_at":           _parse_ts(j.get("published", "")),
            "description_snippet": snippet,
        })
    return jobs


def _fetch_workable_widget(token: str, fetch_details: bool) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    results = r.json().get("jobs", [])
    snippets = (_map_details(lambda j: detail_workable(token, j.get("shortcode", "")), results)
                if fetch_details else [""] * len(results))
    jobs = []
    for j, snippet in zip(results, snippets):
        jobs.append({
            "title":               j.get("title", ""),
            "department":          j.get("department", "") or "",
            "location":            ", ".join(x for x in [j.get("city", ""), j.get("country", "")] if x),
            "apply_url":           j.get("url") or f"https://apply.workable.com/{token}/j/{j.get('shortcode', '')}/",
            "posted_at":           _parse_ts(j.get("published_on") or j.get("created_at") or ""),
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# SmartRecruiters
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_smartrecruiters(token: str, fetch_descriptions: bool = True, fetch_details: bool = False) -> list[dict]:
    base = f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
    postings, offset = [], 0
    while len(postings) < MAX_JOBS_PER_COMPANY:
        r = requests.get(base, params={"limit": 100, "offset": offset}, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        page = data.get("content", [])
        postings.extend(page)
        total = data.get("totalFound", 0) or 0
        offset += len(page)
        if not page or offset >= total or _paging_expired():
            break

    snippets = (_map_details(lambda p: detail_smartrecruiters(token, p.get("id")), postings)
                if fetch_details else [""] * len(postings))
    jobs = []
    for p, snippet in zip(postings, snippets):
        loc = p.get("location") or {}
        loc_s = ", ".join(x for x in [loc.get("city", ""), loc.get("region", ""), loc.get("country", "")] if x)
        if loc.get("remote"):
            loc_s = (loc_s + " (Remote)").strip()
        jobs.append({
            "title":               p.get("name", ""),
            "department":          (p.get("department") or {}).get("label", ""),
            "location":            loc_s,
            "apply_url":           f"https://jobs.smartrecruiters.com/{token}/{p.get('id')}",
            "posted_at":           _parse_ts(p.get("releasedDate", "")),
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Workday
# ─────────────────────────────────────────────────────────────────────────────

WORKDAY_PAGE_SIZE = 20   # the cxs API rejects larger pages


def _fetch_workday(token: str, fetch_descriptions: bool = True, fetch_details: bool = False) -> list[dict]:
    """Workday's candidate-site JSON API (the same calls the careers page
    makes). POST .../wday/cxs/<tenant>/<site>/jobs pages 20 at a time;
    `total` is only reliable on the first page. Some tenants stop serving
    results past a fixed offset on their side; we stop on the first short
    or empty page."""
    host, tenant, site = token.split("|", 2)
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    hdrs = {**HEADERS, "Content-Type": "application/json"}
    postings, offset, total = [], 0, None
    while len(postings) < MAX_JOBS_PER_COMPANY:
        r = requests.post(f"{api}/jobs", json={"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE,
                                               "offset": offset, "searchText": ""},
                          headers=hdrs, timeout=15)
        r.raise_for_status()
        data = r.json()
        page = data.get("jobPostings", []) or []
        if total is None:
            total = data.get("total", 0) or 0
        postings.extend(page)
        offset += WORKDAY_PAGE_SIZE
        if len(page) < WORKDAY_PAGE_SIZE or (total and offset >= total) or _paging_expired():
            break

    snippets = (_map_details(lambda p: detail_workday(host, tenant, site, p.get("externalPath", "")), postings)
                if fetch_details else [""] * len(postings))
    jobs = []
    for p, snippet in zip(postings, snippets):
        path = p.get("externalPath", "")
        if not path:
            continue
        if "myworkdaysite.com" in host:
            apply_url = f"https://{host}/recruiting/{tenant}/{site}{path}"
        else:
            apply_url = f"https://{host}/{site}{path}"
        jobs.append({
            "title":               p.get("title", ""),
            "department":          "",
            "location":            p.get("locationsText", "") or "",
            "apply_url":           apply_url,
            "posted_at":           "",   # Workday gives "Posted 3 Days Ago", not a date
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Oracle Recruiting Cloud (Fusion HCM candidate experience)
# ─────────────────────────────────────────────────────────────────────────────

_ORACLE_DEFAULT_SITES = ("CX_1", "CX", "CX_2", "CX_1001")


def _fetch_oracle(token: str, fetch_descriptions: bool = True, fetch_details: bool = False) -> list[dict]:
    """GET /hcmRestApi/resources/latest/recruitingCEJobRequisitions — the
    public REST resource the candidate-experience site calls. When the site
    number is unknown (only the host was seen) the common defaults are tried.
    NOT LIVE-VERIFIED from this environment; test with a scoped run."""
    host, site = (token.split("|", 1) + [""])[:2]
    sites = [site] if site else list(_ORACLE_DEFAULT_SITES)
    last_err = None
    for s in sites:
        try:
            reqs = _oracle_list(host, s)
        except requests.HTTPError as e:
            last_err = e
            continue
        if reqs or site:
            return _oracle_jobs(host, s, reqs, fetch_descriptions, fetch_details)
    if last_err is not None:
        raise last_err
    return []


def _oracle_list(host: str, site: str) -> list[dict]:
    url = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    out, offset = [], 0
    while len(out) < MAX_JOBS_PER_COMPANY:
        finder = f"findReqs;siteNumber={site},limit=100,offset={offset},sortBy=POSTING_DATES_DESC"
        r = requests.get(url, params={"onlyData": "true", "expand": "requisitionList.secondaryLocations",
                                      "finder": finder}, headers=HEADERS, timeout=15)
        r.raise_for_status()
        items = r.json().get("items", []) or []
        if not items:
            break
        page = items[0].get("requisitionList", []) or []
        total = items[0].get("TotalJobsCount", 0) or 0
        out.extend(page)
        offset += len(page)
        if not page or offset >= total or _paging_expired():
            break
    return out


def _oracle_jobs(host: str, site: str, reqs: list[dict], fetch_descriptions: bool,
                 fetch_details: bool = False) -> list[dict]:
    need_detail = [r for r in reqs if len(r.get("ShortDescriptionStr") or "") < 100]
    detail_map = {}
    if fetch_details and need_detail:
        for r, snip in zip(need_detail, _map_details(lambda q: detail_oracle(host, site, q.get("Id")), need_detail)):
            detail_map[r.get("Id")] = snip

    jobs = []
    for r in reqs:
        rid = r.get("Id")
        if not rid:
            continue
        snippet = detail_map.get(rid) or (make_snippet(r.get("ShortDescriptionStr", ""), is_html=True)
                                          if fetch_descriptions else "")
        jobs.append({
            "title":               r.get("Title", ""),
            "department":          r.get("JobFamily", "") or r.get("Organization", "") or "",
            "location":            r.get("PrimaryLocation", "") or "",
            "apply_url":           f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{rid}",
            "posted_at":           _parse_ts(r.get("PostedDate", "")),
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Recruitee
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_recruitee(token: str, fetch_descriptions: bool = True) -> list[dict]:
    r = requests.get(f"https://{token}.recruitee.com/api/offers/", headers=HEADERS, timeout=15)
    r.raise_for_status()
    jobs = []
    for o in r.json().get("offers", []):
        desc = " ".join(x for x in [o.get("description", ""), o.get("requirements", "")] if x)
        jobs.append({
            "title":               o.get("title", ""),
            "department":          o.get("department", "") or "",
            "location":            o.get("location", "") or ", ".join(x for x in [o.get("city", ""), o.get("country", "")] if x),
            "apply_url":           o.get("careers_url") or o.get("careers_apply_url") or "",
            "posted_at":           _parse_ts(o.get("published_at") or o.get("created_at") or ""),
            "description_snippet": make_snippet(desc, is_html=True) if fetch_descriptions else "",
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Phenom (career sites on the company's own domain: careers.adobe.com,
# jobs.advanceautoparts.com, www.acadiacareers.com ...)
# ─────────────────────────────────────────────────────────────────────────────
#
# Checked 2026-11-11 in Chrome against Adobe, Advance Auto Parts, Chewy,
# Acadia, TJX, United, Humana, PNC and Ecolab:
#   - Every search-results page carries `phApp = phApp || {...}` with
#     widgetApiEndpoint, country, locale, siteType and baseUrl.
#   - POST <widgetApiEndpoint> {"ddoKey": "refineSearch", ...} pages the
#     jobs. No cookies or CSRF token needed.
#   - Page size is capped at 500 (asking for 1000 returns 500).
#   - Paging stops at 9,999 results: from + size must stay under 10,000, or
#     the call returns 0 jobs and totalHits 0. Boards bigger than that
#     (Advance Auto 16,284, TJX 10,049) are split by a facet (state first),
#     whose counts come back when counts=true and all_fields names it.
#   - Each job has descriptionTeaser (200-330 chars on every site checked),
#     so the nightly scrape gets a usable snippet without detail calls.
#     Full text: POST {"ddoKey": "jobDetail", "jobId": ...} -> data.job.description.
#   - Some sites send jobUrl (Adobe, Advance Auto); most don't. Their pages
#     link to <baseUrl>job/<jobId>/<title with each run of non-alphanumerics
#     turned into one "-">.
#
# Token: "<host>|<base path>", e.g. "careers.adobe.com|us/en",
# "jobs.tjx.com|global/en". See platforms.parse_phenom_config().

PHENOM_PAGE_SIZE = 500       # largest page the API serves; see CHANGES_2026-11-11.md for 100 vs 500
PHENOM_RESULT_WINDOW = 9999  # from + size must stay at or under this
PHENOM_SPLIT_FIELDS = ("state", "country", "type", "category", "city")
PHENOM_MAX_BUCKETS = 80      # don't split on a facet with more values than this (one call each)
PHENOM_MAX_PASSES = 3        # paging passes over a search that can't be split further


def _phenom_job_url(base_url: str, job: dict) -> str:
    """Link to one job. jobUrl when the site sends it, otherwise built the
    way Phenom's own pages build it: <baseUrl>job/<jobId>/<Title-Slug>."""
    u = (job.get("jobUrl") or "").strip()
    if u.startswith("http"):
        return u
    job_id = str(job.get("jobId") or "").strip()
    if not job_id:
        return ""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", job.get("title") or "").strip("-")
    base = base_url if base_url.endswith("/") else base_url + "/"
    return f"{base}job/{quote(job_id, safe='')}/{slug}" if slug else f"{base}job/{quote(job_id, safe='')}"


def _phenom_location(job: dict) -> str:
    for k in ("location", "cityStateCountry", "cityState"):
        v = job.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    parts = ", ".join(x for x in (job.get("city"), job.get("state"), job.get("country"))
                      if isinstance(x, str) and x.strip())
    if parts:
        return parts
    multi = job.get("multi_location")
    if isinstance(multi, list) and multi and isinstance(multi[0], str):
        return multi[0]
    if str(job.get("isRemote", "")).lower() in ("yes", "true"):
        return "Remote"
    return ""


def _phenom_config(token: str) -> dict:
    """Site settings for the widgets API: read from the search-results page's
    phApp block, or, if that page can't be read, worked out from the token."""
    from .platforms import parse_phenom_config
    host, _, path = token.partition("|")
    path = path.strip("/")
    page = f"https://{host}/{path + '/' if path else ''}search-results"
    cfg = None
    try:
        r = requests.get(page, headers={**HEADERS, "Accept": "text/html,*/*"}, timeout=15)
        if r.status_code == 200:
            cfg = parse_phenom_config(r.text)
    except requests.RequestException:
        pass
    if not cfg:
        parts = path.split("/")
        country = parts[0] if parts and parts[0] else "us"
        lang = parts[1] if len(parts) > 1 else "en"
        cfg = {"locale": f"{lang}_{country}", "country": country, "siteType": "external",
               "widgetApiEndpoint": f"https://{host}/widgets",
               "baseUrl": f"https://{host}/{path + '/' if path else ''}"}
    return cfg


def _phenom_post(cfg: dict, body: dict) -> dict:
    payload = {"lang": cfg["locale"], "deviceType": "desktop", "country": cfg["country"],
               "siteType": cfg.get("siteType") or "external", **body}
    r = requests.post(cfg["widgetApiEndpoint"], json=payload,
                      headers={**HEADERS, "Content-Type": "application/json"}, timeout=20)
    r.raise_for_status()
    return r.json()


def _phenom_search(cfg: dict, start: int, size: int, selected: Optional[dict] = None,
                   facets: tuple = ()) -> dict:
    body = {"pageName": "search-results", "ddoKey": "refineSearch", "from": start, "size": size,
            "jobs": True, "counts": bool(facets), "all_fields": list(facets), "keywords": "",
            "global": True, "selected_fields": selected or {}}
    rs = _phenom_post(cfg, body).get("refineSearch")
    if not isinstance(rs, dict):
        raise ValueError("widgets response has no refineSearch (not a Phenom search endpoint?)")
    return rs


def _phenom_jobs(rs: dict) -> list:
    return ((rs.get("data") or {}).get("jobs")) or []


def _phenom_key(j: dict):
    return j.get("jobId") or j.get("jobSeqNo") or j.get("title")


class _PhenomRun:
    """One board fetch. Paging a Phenom search is not stable: the order of
    results shifts between calls (no sort fixes it; tried relevance, date,
    title, jobId, jobSeqNo), so paging Advance Auto's Florida jobs, 1,925
    of them 100 at a time, returned only 1,760-1,860 different jobs. A
    search that fits in one page has no such loss, so big searches are
    split by facet until each part fits in one call; parts that can't be
    split are paged up to PHENOM_MAX_PASSES times and the passes merged."""

    def __init__(self, cfg: dict, cap: int, page_size: int):
        self.cfg, self.cap, self.page_size = cfg, cap, page_size
        self.seen: dict = {}
        self.calls = 0
        self.notes: list = []

    def full(self) -> bool:
        return len(self.seen) >= self.cap or _paging_expired()

    def add(self, jobs: list, scope: set) -> int:
        new = 0
        for j in jobs:
            k = _phenom_key(j)
            if not k:
                continue
            scope.add(k)
            if k not in self.seen:
                self.seen[k] = j
                new += 1
        return new

    def search(self, start, size, selected=None, facets=()):
        self.calls += 1
        return _phenom_search(self.cfg, start, size, selected, facets)

    def collect(self, selected: dict, first: Optional[dict] = None) -> int:
        """Get every job matching `selected`. Returns its totalHits."""
        free = tuple(f for f in PHENOM_SPLIT_FIELDS if f not in selected)
        rs = first or self.search(0, self.page_size, selected, free)
        total = rs.get("totalHits") or 0
        scope: set = set()
        page = _phenom_jobs(rs)
        self.add(page, scope)
        if len(scope) >= total or len(page) < min(self.page_size, total) or self.full():
            return total

        # Split on the facet whose biggest part is smallest, if it covers
        # every job in this search and has a manageable number of parts.
        aggs = {a.get("field"): a.get("value") or {}
                for a in ((rs.get("data") or {}).get("aggregations") or []) if isinstance(a, dict)}
        best = None
        for f in free:
            vals = {k: v for k, v in (aggs.get(f) or {}).items() if v}
            if len(vals) < 2 or len(vals) > PHENOM_MAX_BUCKETS or sum(vals.values()) < total:
                continue
            biggest = max(vals.values())
            if biggest < total and (best is None or biggest < best[0]):
                best = (biggest, f, vals)
        if best:
            _, f, vals = best
            for value, _n in sorted(vals.items(), key=lambda kv: kv[1]):
                if self.full():
                    break
                self.collect({**selected, f: [value]})
            return total

        # Can't split: page it, several passes if jobs are still missing.
        want = min(total, PHENOM_RESULT_WINDOW)
        for _pass in range(PHENOM_MAX_PASSES):
            added = 0
            start = len(page) if _pass == 0 else 0
            while start < want and not self.full():
                size = min(self.page_size, PHENOM_RESULT_WINDOW - start)
                chunk = _phenom_jobs(self.search(start, size, selected))
                added += self.add(chunk, scope)
                start += len(chunk)
                if len(chunk) < size:
                    break
            if len(scope) >= want or self.full() or (_pass > 0 and added == 0):
                break
        if len(scope) < want:
            self.notes.append(f"{selected or 'all'}: {len(scope)} of {total}")
        return total


def _fetch_phenom(token: str, fetch_descriptions: bool = True, fetch_details: bool = False,
                  cap: Optional[int] = None, page_size: Optional[int] = None) -> list[dict]:
    """Phenom widgets API. `cap` and `page_size` default to
    PHENOM_MAX_JOBS and PHENOM_PAGE_SIZE (the dry-run tool overrides them)."""
    cap = cap or PHENOM_MAX_JOBS
    page_size = min(page_size or PHENOM_PAGE_SIZE, 500)
    cfg = _phenom_config(token)
    run = _PhenomRun(cfg, cap, page_size)
    total = run.collect({})
    d = getattr(_CALL, "diag", None)
    if d is not None:
        d["phenom"] = f"{len(run.seen)}/{total} jobs, {run.calls} calls"
        if run.notes and len(run.seen) < min(total, cap) and "truncated" not in d:
            d["truncated"] = "phenom searches with jobs missing: " + "; ".join(run.notes[:5])
    seen = run.seen

    results = list(seen.values())[:cap]
    base = cfg.get("baseUrl") or f"https://{token.split('|')[0]}/"
    snippets = [""] * len(results)
    if fetch_details:
        snippets = _map_details(lambda j: detail_phenom(cfg, j.get("jobId")), results)
    jobs = []
    for j, snippet in zip(results, snippets):
        url = _phenom_job_url(base, j)
        if not url:
            continue
        if not snippet and fetch_descriptions:
            snippet = make_snippet(j.get("descriptionTeaser") or "", is_html=True)
        jobs.append({
            "title":               (j.get("title") or "").strip(),
            "department":          j.get("category") or "",
            "location":            _phenom_location(j),
            "apply_url":           url,
            "posted_at":           _parse_ts(j.get("postedDate") or j.get("dateCreated") or ""),
            "description_snippet": snippet,
        })
    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Per-job description calls (used by run_description_backfill.py, and by
# fetch_jobs only when fetch_details=True). Each raises on a transport/HTTP
# error, so the caller can count it as a failed try, and returns "" when the
# job exists but has no description text.
# ─────────────────────────────────────────────────────────────────────────────

DETAIL_TIMEOUT = 15


def _get_json(url: str, **kw):
    r = requests.get(url, headers=HEADERS, timeout=DETAIL_TIMEOUT, **kw)
    r.raise_for_status()
    return r.json()


def detail_workday(host: str, tenant: str, site: str, path: str) -> str:
    if not path:
        return ""
    info = _get_json(f"https://{host}/wday/cxs/{tenant}/{site}{path}").get("jobPostingInfo") or {}
    return make_snippet(info.get("jobDescription", ""), is_html=True)


def detail_smartrecruiters(company: str, posting_id) -> str:
    if not posting_id:
        return ""
    data = _get_json(f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}")
    sections = ((data.get("jobAd") or {}).get("sections") or {})
    parts = [(sections.get(k) or {}).get("text", "") for k in
             ("jobDescription", "qualifications", "companyDescription")]
    return make_snippet(" ".join(x for x in parts if x), is_html=True)


def detail_oracle(host: str, site: str, rid) -> str:
    if not rid:
        return ""
    data = _get_json(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
                     params={"onlyData": "true", "expand": "all",
                             "finder": f'ByIdFinder;Id="{rid}",siteNumber={site}'})
    items = data.get("items", []) or []
    if not items:
        return ""
    d = items[0]
    text = " ".join(x for x in [d.get("ExternalDescriptionStr", ""), d.get("ExternalResponsibilitiesStr", ""),
                                 d.get("ExternalQualificationsStr", "")] if x)
    return make_snippet(text, is_html=True)


def detail_workable(account: str, shortcode: str) -> str:
    """NOT LIVE-VERIFIED."""
    if not shortcode:
        return ""
    data = _get_json(f"https://apply.workable.com/api/v3/accounts/{account}/jobs/{shortcode}")
    description = " ".join(x for x in [data.get("description", ""), data.get("requirements", "")] if x)
    return make_snippet(description or data.get("description_html", ""), is_html=True)


def detail_greenhouse(board: str, job_id: str, eu: bool = False) -> str:
    host = "boards-api.eu.greenhouse.io" if eu else "boards-api.greenhouse.io"
    data = _get_json(f"https://{host}/v1/boards/{board}/jobs/{job_id}")
    return make_snippet(data.get("content", ""), is_html=True)


def detail_lever(company: str, posting_id: str, eu: bool = False) -> str:
    host = "api.eu.lever.co" if eu else "api.lever.co"
    data = _get_json(f"https://{host}/v0/postings/{company}/{posting_id}")
    if data.get("descriptionPlain"):
        return make_snippet(data["descriptionPlain"], is_html=False)
    return make_snippet(data.get("description", ""), is_html=True)


def detail_phenom(cfg_or_token, job_id) -> str:
    """Full description for one Phenom job. Takes the config dict from
    _phenom_config() or a "<host>|<base path>" token. Not in
    _DETAIL_PATTERNS: Phenom job links live on company domains, so a URL
    pattern can't tell them apart from other sites, and the list's
    descriptionTeaser already passes the 100-character bar."""
    if not job_id:
        return ""
    cfg = cfg_or_token if isinstance(cfg_or_token, dict) else _phenom_config(cfg_or_token)
    data = _phenom_post(cfg, {"pageName": "job", "ddoKey": "jobDetail", "jobId": str(job_id)})
    job = (((data.get("jobDetail") or {}).get("data")) or {}).get("job") or {}
    return make_snippet(job.get("description") or "", is_html=True)


_DETAIL_PATTERNS = [
    # Workday: https://tenant.wd5.myworkdayjobs.com/[en-US/]Site/job/...
    (re.compile(r"^https?://(([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([^/?#]+)(/job/[^?#]+)", re.I),
     "workday", lambda m: detail_workday(m.group(1).lower(), m.group(2).lower(), m.group(3), m.group(4))),
    # Workday on myworkdaysite.com: https://wd3.myworkdaysite.com/[en-US/]recruiting/tenant/Site/job/...
    (re.compile(r"^https?://(wd\d+\.myworkdaysite\.com)/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/([^/]+)/([^/?#]+)(/job/[^?#]+)", re.I),
     "workday", lambda m: detail_workday(m.group(1).lower(), m.group(2), m.group(3), m.group(4))),
    (re.compile(r"^https?://(?:jobs|careers)\.smartrecruiters\.com/([^/?#]+)/(\d+)", re.I),
     "smartrecruiters", lambda m: detail_smartrecruiters(m.group(1), m.group(2))),
    (re.compile(r"^https?://([a-z0-9.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[A-Za-z_-]+/sites/([A-Za-z0-9_]+)/job/(\d+)", re.I),
     "oracle", lambda m: detail_oracle(m.group(1).lower(), m.group(2), m.group(3))),
    (re.compile(r"^https?://apply\.workable\.com/([^/?#]+)/j/([A-Za-z0-9]+)", re.I),
     "workable", lambda m: detail_workable(m.group(1), m.group(2))),
    (re.compile(r"^https?://(?:boards|job-boards)\.(eu\.)?greenhouse\.io/([^/?#]+)/jobs/(\d+)", re.I),
     "greenhouse", lambda m: detail_greenhouse(m.group(2), m.group(3), eu=bool(m.group(1)))),
    (re.compile(r"^https?://jobs\.(eu\.)?lever\.co/([^/?#]+)/([0-9a-f-]{36})", re.I),
     "lever", lambda m: detail_lever(m.group(2), m.group(3), eu=bool(m.group(1)))),
]


def detail_source_for_url(apply_url: str) -> Optional[str]:
    """Which API detail_for_url() would use for this apply_url, or None
    when the job page itself has to be fetched."""
    for rx, source, _ in _DETAIL_PATTERNS:
        if rx.match(apply_url or ""):
            return source
    return None


def detail_for_url(apply_url: str) -> Optional[tuple[str, str]]:
    """(source, snippet) from the platform's API for this apply_url, or None
    if no API covers it. Raises on request errors."""
    for rx, source, fn in _DETAIL_PATTERNS:
        m = rx.match(apply_url or "")
        if m:
            return source, fn(m)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(ts_str) -> str:
    """Parse an ISO timestamp string to YYYY-MM-DD."""
    if not ts_str or not isinstance(ts_str, str):
        return ""
    s = ts_str.strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return ""


def _parse_ts_ms(ts_ms: int) -> str:
    """Parse Unix milliseconds to YYYY-MM-DD."""
    if not ts_ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""
