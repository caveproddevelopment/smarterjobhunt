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

Description snippets matter beyond search: the backend's auto-clean
(routes/staging.py) only auto-approves a staged row with >= 100 chars of
raw_text. Platforms whose list endpoint has no description (Workday,
SmartRecruiters, Oracle, Workable) get a per-job detail call, capped at
DETAIL_FETCH_CAP jobs per company and run DETAIL_CONCURRENCY at a time.

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

DETAIL_FETCH_CAP = 60        # max per-job detail requests per company
DETAIL_CONCURRENCY = 5
MAX_JOBS_PER_COMPANY = 1000  # pagination safety cap


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def fetch_jobs(ats: str, token: str, fetch_descriptions: bool = True,
               diag: Optional[dict] = None) -> list[dict]:
    """Fetch all open jobs from the given ATS. Never raises: errors are
    printed, recorded in `diag` (fetch_status / fetch_error), and [] returned."""
    fn = {
        "greenhouse":      lambda t, fd: _fetch_greenhouse(t, fd, eu=False),
        "greenhouse_eu":   lambda t, fd: _fetch_greenhouse(t, fd, eu=True),
        "lever":           lambda t, fd: _fetch_lever(t, fd, eu=False),
        "lever_eu":        lambda t, fd: _fetch_lever(t, fd, eu=True),
        "ashby":           _fetch_ashby,
        "workable":        _fetch_workable,
        "smartrecruiters": _fetch_smartrecruiters,
        "workday":         _fetch_workday,
        "oracle":          _fetch_oracle,
        "recruitee":       _fetch_recruitee,
    }.get(ats)

    if fn is None:
        if diag is not None:
            diag["fetch_error"] = f"unsupported ats: {ats}"
        return []

    try:
        return fn(token, fetch_descriptions)
    except Exception as e:
        print(f"[ats_api] Error fetching from {ats}/{token}: {e}")
        if diag is not None:
            resp = getattr(e, "response", None)
            diag["fetch_status"] = getattr(resp, "status_code", None)
            diag["fetch_error"] = f"{type(e).__name__}: {e}"[:200]
        return []


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

def _fetch_workable(token: str, fetch_descriptions: bool = True) -> list[dict]:
    """v3 search endpoint first (what apply.workable.com itself uses), then
    the v1 widget endpoint if v3 errors or returns nothing."""
    v3_error = None
    try:
        jobs = _fetch_workable_v3(token, fetch_descriptions)
        if jobs:
            return jobs
    except Exception as e:
        v3_error = e
    try:
        jobs = _fetch_workable_widget(token, fetch_descriptions)
    except Exception:
        if v3_error is not None:
            raise v3_error
        raise
    return jobs


def _fetch_workable_v3(token: str, fetch_descriptions: bool) -> list[dict]:
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
    r = requests.post(url, json={"query": "", "location": [], "department": [], "worktype": [], "remote": []},
                      headers={**HEADERS, "Content-Type": "application/json"}, timeout=15)
    r.raise_for_status()
    results = r.json().get("results", [])

    snippets = (_map_details(lambda j: _fetch_workable_detail(token, j.get("shortcode", "")), results)
                if fetch_descriptions else [""] * len(results))
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


def _fetch_workable_widget(token: str, fetch_descriptions: bool) -> list[dict]:
    url = f"https://apply.workable.com/api/v1/widget/accounts/{token}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    results = r.json().get("jobs", [])
    snippets = (_map_details(lambda j: _fetch_workable_detail(token, j.get("shortcode", "")), results)
                if fetch_descriptions else [""] * len(results))
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


def _fetch_workable_detail(token: str, shortcode: str) -> str:
    """One extra GET per job. NOT LIVE-VERIFIED; fails soft to ""."""
    if not shortcode:
        return ""
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs/{shortcode}"
    r = requests.get(url, headers=HEADERS, timeout=10)
    if r.status_code != 200:
        return ""
    data = r.json()
    description = " ".join(x for x in [data.get("description", ""), data.get("requirements", "")] if x)
    return make_snippet(description or data.get("description_html", ""), is_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# SmartRecruiters
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_smartrecruiters(token: str, fetch_descriptions: bool = True) -> list[dict]:
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
        if not page or offset >= total:
            break

    def detail(p):
        rr = requests.get(f"{base}/{p.get('id')}", headers=HEADERS, timeout=10)
        if rr.status_code != 200:
            return ""
        sections = ((rr.json().get("jobAd") or {}).get("sections") or {})
        parts = [(sections.get(k) or {}).get("text", "") for k in
                 ("jobDescription", "qualifications", "companyDescription")]
        return make_snippet(" ".join(x for x in parts if x), is_html=True)

    snippets = _map_details(detail, postings) if fetch_descriptions else [""] * len(postings)
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

def _fetch_workday(token: str, fetch_descriptions: bool = True) -> list[dict]:
    """Workday's candidate-site JSON API (the same calls the careers page
    makes). POST .../wday/cxs/<tenant>/<site>/jobs pages 20 at a time;
    `total` is only reliable on the first page."""
    host, tenant, site = token.split("|", 2)
    api = f"https://{host}/wday/cxs/{tenant}/{site}"
    hdrs = {**HEADERS, "Content-Type": "application/json"}
    postings, offset, total = [], 0, None
    while len(postings) < MAX_JOBS_PER_COMPANY:
        r = requests.post(f"{api}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": ""},
                          headers=hdrs, timeout=15)
        r.raise_for_status()
        data = r.json()
        page = data.get("jobPostings", []) or []
        if total is None:
            total = data.get("total", 0) or 0
        postings.extend(page)
        offset += 20
        if len(page) < 20 or (total and offset >= total):
            break

    def detail(p):
        path = p.get("externalPath", "")
        if not path:
            return ""
        rr = requests.get(f"{api}{path}", headers=HEADERS, timeout=10)
        if rr.status_code != 200:
            return ""
        info = rr.json().get("jobPostingInfo") or {}
        return make_snippet(info.get("jobDescription", ""), is_html=True)

    snippets = _map_details(detail, postings) if fetch_descriptions else [""] * len(postings)
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


def _fetch_oracle(token: str, fetch_descriptions: bool = True) -> list[dict]:
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
            return _oracle_jobs(host, s, reqs, fetch_descriptions)
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
        if not page or offset >= total:
            break
    return out


def _oracle_jobs(host: str, site: str, reqs: list[dict], fetch_descriptions: bool) -> list[dict]:
    def detail(req):
        rid = req.get("Id")
        rr = requests.get(f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails",
                          params={"onlyData": "true", "expand": "all",
                                  "finder": f'ByIdFinder;Id="{rid}",siteNumber={site}'},
                          headers=HEADERS, timeout=10)
        if rr.status_code != 200:
            return ""
        items = rr.json().get("items", []) or []
        if not items:
            return ""
        d = items[0]
        text = " ".join(x for x in [d.get("ExternalDescriptionStr", ""), d.get("ExternalResponsibilitiesStr", ""),
                                     d.get("ExternalQualificationsStr", "")] if x)
        return make_snippet(text, is_html=True)

    need_detail = [r for r in reqs if len(r.get("ShortDescriptionStr") or "") < 100]
    detail_map = {}
    if fetch_descriptions and need_detail:
        for r, snip in zip(need_detail, _map_details(detail, need_detail)):
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
