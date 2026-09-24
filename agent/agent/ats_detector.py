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

# Path segments that are NOT a company's board token. Without this list the
# patterns below happily capture "embed" from boards.greenhouse.io/embed/...,
# "j" from apply.workable.com/j/<shortcode>, "api" from apply.workable.com/api/...,
# and then the ATS API 404s on a board that doesn't exist.
_RESERVED_TOKENS = {
    "greenhouse": {"embed", "v1", "jobs", "api", "boards", "job_board", "js", "assets", "static", "widget"},
    "lever":      {"jobs", "api", "v0", "postings", "assets", "static"},
    "ashby":      {"api", "jobs", "embed", "assets", "static"},
    "workable":   {"j", "api", "jobs", "assets", "static", "widget"},
}

# Greenhouse's embed form keeps the real board token in a query parameter:
#   boards.greenhouse.io/embed/job_board?for=<token>   (or .../job_board/js?for=<token>)
_GH_EMBED_FOR = re.compile(
    r"greenhouse\.io/embed/job_board[^\"'\s<>]*?[?&;]for=([A-Za-z0-9_-]+)", re.IGNORECASE
)

# Careers subdomains tried (in addition to CAREER_PATHS) when hunting for a careers page.
CAREER_SUBDOMAINS = ("careers", "jobs")

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


def detect_ats(company_name: str, website: Optional[str] = None,
               diag: Optional[dict] = None) -> ATSResult:
    """
    Detect ATS for a company. All independent network probes (known ATS
    APIs by guessed slug, plus career-page path guesses) run concurrently.

    `diag` (optional, diagnostics only — never changes behavior): a dict
    that gets filled in with how the decision was reached:
      slug_tried       the name-derived slug probed against Greenhouse/Lever/Ashby
      homepage_status  HTTP status (or "error: <ExcType>") of the homepage GET
      detected_via     known_api_probe | homepage_scan |
                       career_path_guess+page_scan | career_path_guess | none
    """
    if diag is None:
        diag = {}
    slug = _slugify(company_name)
    diag["slug_tried"] = slug

    known = _probe_known_apis_parallel(slug)
    if known:
        ats, token = known
        diag["detected_via"] = "known_api_probe"
        return ATSResult(ats=ats, token=token, can_api=True)

    if website:
        result = _scan_website(website, diag=diag)
        if result:
            diag["detected_via"] = "homepage_scan"
            return result

    careers_url = _find_careers_page_parallel(website or f"https://www.{slug}.com")
    if careers_url:
        result = _scan_page(careers_url)
        if result:
            result.careers_url = careers_url
            diag["detected_via"] = "career_path_guess+page_scan"
            return result
        diag["detected_via"] = "career_path_guess"
        return ATSResult(ats="unknown", token=None, can_api=False, careers_url=careers_url)

    diag["detected_via"] = "none"
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


def _scan_website(url: str, diag: Optional[dict] = None) -> Optional[ATSResult]:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if diag is not None:
            diag["homepage_status"] = str(r.status_code)
        if r.status_code != 200:
            return None
        return _extract_ats_from_html(r.text, r.url)
    except Exception as e:
        if diag is not None:
            diag["homepage_status"] = f"error: {type(e).__name__}"
        return None


def _scan_page(url: str) -> Optional[ATSResult]:
    return _scan_website(url)


def _url_around(html: str, idx: int) -> str:
    """The full URL surrounding position `idx` in `html` (delimited by quotes,
    whitespace, brackets)."""
    delims = "\"'<> \t\r\n()\\"
    lo = idx
    while lo > 0 and html[lo - 1] not in delims:
        lo -= 1
    hi = idx
    while hi < len(html) and html[hi] not in delims:
        hi += 1
    url = html[lo:hi].replace("&amp;", "&")
    if url.startswith("http"):
        return url
    return "https://" + url.lstrip("/")


def _extract_ats_from_html(html: str, base_url: str) -> Optional[ATSResult]:
    # 1) Greenhouse embed: the token lives in ?for=, not in the path.
    m = _GH_EMBED_FOR.search(html)
    if m:
        return ATSResult(ats="greenhouse", token=m.group(1), can_api=True)

    for pattern, ats_name in ATS_PATTERNS:
        for match in re.finditer(pattern, html, re.IGNORECASE):
            token = match.group(1) if match.lastindex and match.lastindex >= 1 else None
            can_api = ats_name in ("greenhouse", "lever", "ashby", "workable")

            if can_api:
                # Skip path segments that aren't board tokens ("embed", "j", "api", ...).
                if not token or token.lower() in _RESERVED_TOKENS.get(ats_name, ()):
                    continue
                return ATSResult(ats=ats_name, token=token, can_api=True)

            # Workday / Rippling / BambooHR: no public API here, but hand back the
            # URL we found so the page scraper has something to scrape (before,
            # careers_url was left empty and these companies were silently skipped).
            return ATSResult(ats=ats_name, token=None, can_api=False,
                             careers_url=_url_around(html, match.start()))
    return None


def detect_ats_from_url(url: str) -> Optional[ATSResult]:
    """If `url` itself is (or embeds) a supported ATS board URL, return the
    API-capable ATSResult for it; otherwise None."""
    res = _extract_ats_from_html(url or "", url or "")
    if res and res.can_api and res.token:
        return res
    return None


def _try_career_path(base_url: str, path: str) -> Optional[str]:
    url = base_url.rstrip("/") + path
    try:
        r = requests.get(url, headers=HEADERS, timeout=8, allow_redirects=True)
        if r.status_code == 200 and _redirected_to_homepage(r.url, base_url, path):
            return None
        if r.status_code == 200:
            return r.url
    except Exception:
        pass
    return None


def _redirected_to_homepage(final_url: str, base_url: str, requested_path: str) -> bool:
    """Reject career-path requests that simply redirect back home."""
    if requested_path == "/":
        return False
    final = urlparse(final_url)
    base = urlparse(base_url)
    return (
        final.netloc.lower() == base.netloc.lower()
        and final.path.rstrip("/") == ""
        and not final.query
        and not final.fragment
    )


def _find_careers_page_parallel(base_url: str) -> Optional[str]:
    """Try all common career page paths concurrently; return the first hit
    in CAREER_PATHS priority order, not the first thread to finish."""
    if not base_url.startswith("http"):
        base_url = "https://" + base_url

    # Candidates in priority order: the usual paths on the same host, then
    # careers./jobs. subdomains (many companies host careers there, so the
    # path guesses on the main site 404).
    bare_host = re.sub(r"^www\.", "", urlparse(base_url).netloc.lower())
    candidates = [(base_url, path) for path in CAREER_PATHS]
    if bare_host:
        candidates += [(f"https://{sub}.{bare_host}", "/") for sub in CAREER_SUBDOMAINS]

    with ThreadPoolExecutor(max_workers=len(candidates)) as ex:
        futures = {ex.submit(_try_career_path, base, path): i for i, (base, path) in enumerate(candidates)}
        results = {}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()

    for i in range(len(candidates)):
        if results.get(i):
            return results[i]
    return None
