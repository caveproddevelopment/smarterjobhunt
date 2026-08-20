"""
ATS Detector — given a company domain, determines which Applicant
Tracking System (ATS) they use and returns the ATS token/slug needed
to call the public job-board API.

Supported ATS:
  - Greenhouse  → boards.greenhouse.io/{token}
  - Lever       → jobs.lever.co/{token}
  - Ashby       → jobs.ashbyhq.com/{token}
  - Workday     → (detected but no public API; returns scrape flag)
  - Rippling     → (detected but no public API; returns scrape flag)
  - Unknown     → returns scrape flag

Perf note: the original version probed Greenhouse -> Lever -> Ashby
sequentially, then tried up to 8 career-page URL guesses one at a time
with a 0.3s sleep between each. All of these are independent network
calls, so they now fire concurrently via a small thread pool and the
first one that resolves wins. This turns a worst-case ~8 sequential
requests + 2.4s of sleep into a single round-trip time per company.
"""

import re
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from typing import Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

ATS_PATTERNS = [
    (r"boards\.greenhouse\.io/([a-z0-9_-]+)", "greenhouse"),
    (r"job-boards\.greenhouse\.io/([a-z0-9_-]+)", "greenhouse"),
    (r"jobs\.lever\.co/([a-z0-9_-]+)", "lever"),
    (r"jobs\.ashbyhq\.com/([a-z0-9_-]+)", "ashby"),
    (r"myworkdayjobs\.com", "workday"),
    (r"app\.rippling\.com/job-board", "rippling"),
    (r"bamboohr\.com/jobs", "bamboohr"),
    (r"apply\.workable\.com/([a-z0-9_-]+)", "workable"),
]

CAREER_PATHS = [
    "/careers", "/jobs", "/about/careers", "/company/careers",
    "/about/jobs", "/join-us", "/work-with-us", "/open-positions",
]


class ATSResult:
    def __init__(self, ats: str, token: Optional[str], can_api: bool, careers_url: Optional[str] = None):
        self.ats = ats
        self.token = token
        self.can_api = can_api
        self.careers_url = careers_url

    def __repr__(self):
        return f"ATSResult(ats={self.ats}, token={self.token}, can_api={self.can_api})"


def detect_ats(company_name: str, website: Optional[str] = None) -> ATSResult:
    """
    Detect ATS for a company. All independent network probes (known ATS
    APIs by guessed slug, plus career-page path guesses) run concurrently.
    """
    slug = _slugify(company_name)

    known = _probe_known_apis_parallel(slug)
    if known:
        ats, token = known
        return ATSResult(ats=ats, token=token, can_api=True)

    if website:
        result = _scan_website(website)
        if result:
            return result

    careers_url = _find_careers_page_parallel(website or f"https://www.{slug}.com")
    if careers_url:
        result = _scan_page(careers_url)
        if result:
            result.careers_url = careers_url
            return result
        return ATSResult(ats="unknown", token=None, can_api=False, careers_url=careers_url)

    return ATSResult(ats="unknown", token=None, can_api=False)


def _slugify(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s.strip())
    s = re.sub(r"-+", "-", s)
    return s


def _probe_one_api(ats: str, slug: str) -> Optional[tuple[str, str]]:
    urls = {
        "greenhouse": (f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", "jobs"),
        "lever":      (f"https://api.lever.co/v0/postings/{slug}?mode=json", None),
        "ashby":      (f"https://api.ashbyhq.com/posting-api/job-board/{slug}", "jobPostings"),
    }
    url, key = urls[ats]
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code != 200:
            return None
        data = r.json()
        if ats == "lever":
            ok = isinstance(data, list)
        else:
            ok = key in data
        return (ats, slug) if ok else None
    except Exception:
        return None


def _probe_known_apis_parallel(slug: str) -> Optional[tuple[str, str]]:
    """Probe Greenhouse / Lever / Ashby concurrently instead of one-at-a-time."""
    # Priority order preserved: if multiple match (rare), prefer greenhouse > lever > ashby
    priority = {"greenhouse": 0, "lever": 1, "ashby": 2}
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_probe_one_api, ats, slug): ats for ats in priority}
        results = []
        for fut in as_completed(futures):
            res = fut.result()
            if res:
                results.append(res)
    if not results:
        return None
    results.sort(key=lambda r: priority[r[0]])
    return results[0]


def _scan_website(url: str) -> Optional[ATSResult]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return None
        return _extract_ats_from_html(r.text, r.url)
    except Exception:
        return None


def _scan_page(url: str) -> Optional[ATSResult]:
    return _scan_website(url)


def _extract_ats_from_html(html: str, base_url: str) -> Optional[ATSResult]:
    for pattern, ats_name in ATS_PATTERNS:
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            token = match.group(1) if match.lastindex and match.lastindex >= 1 else None
            can_api = ats_name in ("greenhouse", "lever", "ashby", "workable")
            return ATSResult(ats=ats_name, token=token, can_api=can_api)
    return None


def _try_career_path(base_url: str, path: str) -> Optional[str]:
    url = base_url.rstrip("/") + path
    try:
        r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if r.status_code == 200:
            return r.url
    except Exception:
        pass
    return None


def _find_careers_page_parallel(base_url: str) -> Optional[str]:
    """Try all common career page paths concurrently; return the first hit
    in CAREER_PATHS priority order, not the first thread to finish."""
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    with ThreadPoolExecutor(max_workers=len(CAREER_PATHS)) as ex:
        futures = {ex.submit(_try_career_path, base_url, path): path for path in CAREER_PATHS}
        results = {}
        for fut in as_completed(futures):
            path = futures[fut]
            results[path] = fut.result()

    for path in CAREER_PATHS:
        if results.get(path):
            return results[path]
    return None
