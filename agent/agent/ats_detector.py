"""
ATS Detector — given a company domain, determines which Applicant
Tracking System (ATS) they use and returns the ATS token/slug needed
to call the public job-board API.

Supported ATS with a JSON API adapter (see ats_api.py and platforms.py):
  Greenhouse (US + EU), Lever (US + EU), Ashby, Workable, SmartRecruiters,
  Workday, Oracle Recruiting Cloud, Recruitee.
Every other known hiring platform (Darwinbox, Keka, PeopleStrong, ...) is
returned with can_api=False and a careers_url pointing at the platform, so
the browser scraper goes straight there.

Perf note: the original version probed Greenhouse -> Lever -> Ashby
sequentially, then tried up to 8 career-page URL guesses one at a time
with a 0.3s sleep between each. All of these are independent network
calls, so they now fire concurrently via a small thread pool and the
first one that resolves wins.

2026-10-13 changes (7 Oct India run analysis):
  - Ashby probe looked for a "jobPostings" key; the public posting API
    returns "jobs". The probe could never match, for any company. Fixed.
  - URL scanning runs on unescaped page source (HTML entities, JSON-escaped
    slashes), so URLs inside JSON blobs are found whole.
  - Greenhouse/Lever EU hosts, Workday, SmartRecruiters, Oracle and
    Recruitee are recognised as API-capable.
  - Career-path guesses are validated (platforms.classify_page): images,
    404 pages served as 200, error routes, login pages, parked domains,
    redirects home or off-site are rejected instead of accepted.
  - Sites that answer 200 for any path are detected with a random-path
    probe; on those, a guess only counts if the page actually talks about
    careers/jobs.
  - More path guesses (/career, /recruitment, /our-people, /life-at-<slug>,
    .html variants, /en/careers ...), then sitemap.xml.
"""

import random
import re
import string
import time
import xml.etree.ElementTree as ET
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from typing import Optional

from .platforms import (
    parse_ats_url, platform_for_url, unescape_for_scan, classify_page,
    extract_title_and_heading, visible_text_sample, API_ATS, host_of,
    same_company_site, PLATFORM_HOSTS,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Kept for backwards compatibility with anything importing it.
_RESERVED_TOKENS = {
    "greenhouse": {"embed", "v1", "jobs", "api", "boards", "job_board", "js", "assets", "static", "widget"},
    "lever":      {"jobs", "api", "v0", "postings", "assets", "static"},
    "ashby":      {"api", "jobs", "embed", "assets", "static"},
    "workable":   {"j", "api", "jobs", "assets", "static", "widget"},
}

# Careers subdomains tried (in addition to CAREER_PATHS) when hunting for a careers page.
CAREER_SUBDOMAINS = ("careers", "jobs", "career")

# Priority order matters: the first validated hit wins.
CAREER_PATHS = [
    "/careers", "/career", "/jobs", "/about/careers", "/company/careers", "/about-us/careers",
    "/about/jobs", "/join-us", "/join", "/work-with-us", "/open-positions", "/current-openings",
    "/recruitment", "/recruitments", "/our-people", "/people", "/hiring",
    "/careers.html", "/career.html", "/en/careers", "/in/careers", "/en-in/careers",
]

# Sitemap lookup budget (seconds) — sitemaps can be large and nested.
SITEMAP_BUDGET_SECONDS = 15
_SITEMAP_CAREER = re.compile(
    r"/(careers?|jobs?|join-us|work-with-us|recruitments?|current-openings|vacanc(y|ies)|"
    r"openings|life-at-[a-z0-9-]+|our-people)(/|\.html?|\.page|\.aspx|$)", re.I)

# Kept for backwards compatibility (old callers / tests).
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


class ATSResult:
    def __init__(self, ats: str, token: Optional[str], can_api: bool, careers_url: Optional[str] = None):
        self.ats = ats
        self.token = token
        self.can_api = can_api
        self.careers_url = careers_url

    def __repr__(self):
        return f"ATSResult(ats={self.ats}, token={self.token}, can_api={self.can_api}, careers_url={self.careers_url})"


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
                       career_path_guess+page_scan | career_path_guess |
                       sitemap+page_scan | sitemap | none
      rejected_guesses up to 8 "path -> reason" strings for guesses rejected
                       by page validation
      catch_all_site   True if the site answers 200 for a random path
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

    base = website or f"https://www.{slug}.com"
    careers_url = _find_careers_page_parallel(base, slug=slug, diag=diag)
    via = "career_path_guess"
    if not careers_url:
        careers_url = _find_careers_via_sitemap(base, diag=diag)
        via = "sitemap"
    if careers_url:
        result = _scan_page(careers_url)
        if result:
            if not result.careers_url:
                result.careers_url = careers_url
            diag["detected_via"] = f"{via}+page_scan"
            return result
        diag["detected_via"] = via
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
        # The public posting API returns {"jobs": [...], "apiVersion": ...}.
        # (Was "jobPostings" — never present, so this probe never matched.)
        "ashby":      (f"https://api.ashbyhq.com/posting-api/job-board/{slug}", "jobs"),
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
            ok = isinstance(data, dict) and (key in data or "jobPostings" in data)
        return (ats, slug) if ok else None
    except Exception:
        return None


def _probe_known_apis_parallel(slug: str) -> Optional[tuple[str, str]]:
    """Probe Greenhouse / Lever / Ashby concurrently instead of one-at-a-time."""
    if not slug:
        return None
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


def _get(url: str, timeout: int = 10):
    return requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)


def _scan_website(url: str, diag: Optional[dict] = None) -> Optional[ATSResult]:
    if not url.startswith("http"):
        url = "https://" + url
    try:
        r = _get(url, timeout=10)
        if diag is not None:
            diag["homepage_status"] = str(r.status_code)
            if host_of(r.url) and host_of(r.url) != host_of(url):
                diag["homepage_final_url"] = r.url[:200]
        if r.status_code != 200:
            return None
        # A homepage that itself redirected to a hiring platform.
        res = _ats_result_for_url(r.url)
        if res:
            return res
        return _extract_ats_from_html(r.text, r.url)
    except Exception as e:
        if diag is not None:
            diag["homepage_status"] = f"error: {type(e).__name__}"
        return None


def _scan_page(url: str) -> Optional[ATSResult]:
    return _scan_website(url)


def _url_around(html: str, idx: int) -> str:
    """The full URL surrounding position `idx` in `html` (delimited by quotes,
    whitespace, brackets). Run on unescape_for_scan() output."""
    delims = "\"'<> \t\r\n()\\,;{}[]"
    lo = idx
    while lo > 0 and html[lo - 1] not in delims:
        lo -= 1
    hi = idx
    while hi < len(html) and html[hi] not in delims:
        hi += 1
    url = html[lo:hi]
    if url.startswith("http"):
        return url
    return "https://" + url.lstrip("/")


def _ats_result_for_url(url: str) -> Optional[ATSResult]:
    """ATSResult for a URL that IS a hiring-platform page, else None."""
    if not url:
        return None
    hit = parse_ats_url(url)
    if hit and hit[0] in API_ATS:
        return ATSResult(ats=hit[0], token=hit[1], can_api=True, careers_url=url)
    plat = platform_for_url(url)
    if plat:
        return ATSResult(ats=plat, token=None, can_api=False, careers_url=url)
    return None


# href/src/action attribute values (after unescaping), for platforms we can
# only scrape: only trust a platform host when the page actually links to or
# embeds it, not when it's merely mentioned in text.
_ATTR_URL = re.compile(r"""(?:href|src|action|data-src|data-url)\s*=\s*["']([^"']+)["']""", re.I)
_ABS_URL = re.compile(r"""https?://[^\s"'<>\\(){}\[\],;]+""", re.I)
_PLATFORM_SUFFIXES = tuple(s for s, _ in PLATFORM_HOSTS)


def _extract_ats_from_html(html: str, base_url: str) -> Optional[ATSResult]:
    """Find an ATS / hiring platform referenced by a page.

    1) API-capable boards anywhere in the source (incl. JSON blobs).
    2) Other hiring platforms, but only from href/src/action attributes.
    """
    if not html:
        return None
    text = unescape_for_scan(html)

    hit = parse_ats_url(text)
    if hit and hit[0] in API_ATS:
        ats, token = hit
        return ATSResult(ats=ats, token=token, can_api=True)

    # Legacy non-API markers that used to hand back a scrape URL.
    for m in re.finditer(r"app\.rippling\.com/job-board|ats\.rippling\.com|bamboohr\.com/(jobs|careers)", text, re.I):
        name = "rippling" if "rippling" in m.group(0).lower() else "bamboohr"
        return ATSResult(ats=name, token=None, can_api=False, careers_url=_url_around(text, m.start()))

    for m in _ATTR_URL.finditer(text):
        u = m.group(1).strip()
        if u.startswith("//"):
            u = "https:" + u
        if not u.startswith("http"):
            continue
        plat = platform_for_url(u)
        if plat:
            return ATSResult(ats=plat, token=None, can_api=False, careers_url=u)
    return None


def detect_ats_from_url(url: str) -> Optional[ATSResult]:
    """If `url` itself is (or embeds) a supported ATS board URL, return the
    API-capable ATSResult for it; otherwise None."""
    hit = parse_ats_url(url or "")
    if hit and hit[0] in API_ATS:
        return ATSResult(ats=hit[0], token=hit[1], can_api=True, careers_url=url)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Careers-page guessing (plain requests)
# ─────────────────────────────────────────────────────────────────────────────

_CAREER_HEADING = re.compile(r"career|job|opening|vacanc|recruit|hiring|join|कैरियर|नौकरी|भर्ती", re.I)


def _fetch_and_validate(url: str, company_host: str, catch_all: bool = False) -> tuple[Optional[str], Optional[str]]:
    """GET `url`; return (final_url, None) if it's a usable careers page,
    else (None, reason)."""
    final, reason, heading = _fetch_check(url, company_host)
    if final and catch_all and not _CAREER_HEADING.search(heading):
        return None, "catch_all_no_career_heading"
    return final, reason


def _fetch_check(url: str, company_host: str) -> tuple[Optional[str], Optional[str], str]:
    """(final_url or None, reject reason or None, "title h1")."""
    try:
        r = _get(url, timeout=8)
    except Exception as e:
        return None, f"error:{type(e).__name__}", ""
    if r.status_code != 200:
        return None, f"http_{r.status_code}", ""
    ctype = r.headers.get("content-type", "")
    body = r.text[:400_000] if (not ctype or "html" in ctype.lower()) else ""
    title, h1 = extract_title_and_heading(body)
    sample = visible_text_sample(body)
    reason = classify_page(url, r.url, r.status_code, ctype, title, h1, sample,
                           company_host=company_host, require_career_words=True)
    if reason:
        return None, reason, f"{title} {h1}"
    return r.url, None, f"{title} {h1}"


def _try_career_path(base_url: str, path: str, company_host: str = "",
                     catch_all: bool = False) -> Optional[str]:
    url = base_url.rstrip("/") + path
    final, _reason = _fetch_and_validate(url, company_host or host_of(base_url), catch_all)
    return final


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


def _is_catch_all(base_url: str) -> bool:
    """True if the site returns a normal-looking 200 page for a path that
    cannot exist (BookMyShow, MCX, IFCI ... in the 7 Oct findings)."""
    junk = "/" + "".join(random.choices(string.ascii_lowercase, k=14)) + "-nx"
    try:
        r = _get(base_url.rstrip("/") + junk, timeout=8)
    except Exception:
        return False
    if r.status_code != 200:
        return False
    title, h1 = extract_title_and_heading(r.text[:200_000])
    reason = classify_page(base_url + junk, r.url, 200, r.headers.get("content-type", ""),
                           title, h1, "", require_career_words=False)
    # If our junk path got recognised as a 404/error/home redirect, the site
    # is honest about missing pages and normal validation is enough.
    return reason is None


def _find_careers_page_parallel(base_url: str, slug: str = "",
                                diag: Optional[dict] = None) -> Optional[str]:
    """Try all common career page paths concurrently; return the first
    *validated* hit in CAREER_PATHS priority order."""
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    company_host = host_of(base_url)
    bare_host = re.sub(r"^www\.", "", company_host)

    paths = list(CAREER_PATHS)
    if slug:
        paths.append(f"/life-at-{slug}")
    candidates = [(base_url, p) for p in paths]
    if bare_host:
        candidates += [(f"https://{sub}.{bare_host}", "/") for sub in CAREER_SUBDOMAINS]

    with ThreadPoolExecutor(max_workers=len(candidates) + 1) as ex:
        catch_all_f = ex.submit(_is_catch_all, base_url)
        futures = {ex.submit(_fetch_check, b.rstrip("/") + p, company_host): i
                   for i, (b, p) in enumerate(candidates)}
        raw = {}
        for fut in as_completed(futures):
            raw[futures[fut]] = fut.result()
        catch_all = catch_all_f.result()
    if diag is not None:
        diag["catch_all_site"] = catch_all

    results = {}
    for i, (final, reason, heading) in raw.items():
        # Catch-all is a property of the main host only; careers./jobs.
        # subdomains are judged on their own.
        same_host = host_of(candidates[i][0]) == company_host
        if final and catch_all and same_host and not _CAREER_HEADING.search(heading):
            final, reason = None, "catch_all_no_career_heading"
        results[i] = (final, reason)

    rejected = []
    for i in range(len(candidates)):
        final, reason = results.get(i, (None, None))
        if final:
            if diag is not None and rejected:
                diag["rejected_guesses"] = rejected[:8]
            return final
        if reason and not reason.startswith(("http_404", "error:")) and len(rejected) < 8:
            rejected.append(f"{candidates[i][1] if candidates[i][1] != '/' else candidates[i][0]} -> {reason}")
    if diag is not None and rejected:
        diag["rejected_guesses"] = rejected
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Sitemap lookup
# ─────────────────────────────────────────────────────────────────────────────

def _sitemap_locs(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemap_urls) from a sitemap or sitemap index."""
    pages, children = [], []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:
        # Not well-formed: fall back to a regex over <loc> tags.
        locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text or "", re.I)
        return [l for l in locs if not l.lower().endswith(".xml")], [l for l in locs if l.lower().endswith(".xml")]
    tag = root.tag.lower()
    for el in root.iter():
        if el.tag.lower().endswith("loc") and el.text:
            (children if tag.endswith("sitemapindex") else pages).append(el.text.strip())
    return pages, children


def pick_careers_from_sitemap(urls: list[str], company_host: str) -> Optional[str]:
    """Shortest same-site URL whose path looks like a careers page. Pure."""
    best = None
    for u in urls:
        h = host_of(u)
        if company_host and h and not same_company_site(h, company_host):
            continue
        path = urlparse(u).path or ""
        if not _SITEMAP_CAREER.search(path):
            continue
        # Prefer a listing page over an individual job/notice page.
        depth = path.strip("/").count("/")
        score = (depth, len(path))
        if best is None or score < best[0]:
            best = (score, u)
    return best[1] if best else None


def _find_careers_via_sitemap(base_url: str, diag: Optional[dict] = None) -> Optional[str]:
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    p = urlparse(base_url)
    root = f"{p.scheme}://{p.netloc}"
    company_host = host_of(base_url)
    deadline = time.monotonic() + SITEMAP_BUDGET_SECONDS

    queue = [root + "/sitemap.xml", root + "/sitemap_index.xml"]
    try:
        r = _get(root + "/robots.txt", timeout=6)
        if r.status_code == 200:
            queue = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", r.text)[:3] + queue
    except Exception:
        pass

    seen, all_pages, fetched = set(), [], 0
    while queue and fetched < 8 and time.monotonic() < deadline:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = _get(sm, timeout=6)
            fetched += 1
            if r.status_code != 200 or "<" not in r.text[:200]:
                continue
            pages, children = _sitemap_locs(r.text[:3_000_000])
            all_pages.extend(pages)
            # Page/"pages"-named child sitemaps first; skip product/blog dumps.
            children.sort(key=lambda c: (0 if re.search(r"page|career|job|main|static", c, re.I) else 1))
            queue.extend(c for c in children[:6]
                         if not re.search(r"product|blog|post|news|image|video|tag|categor", c, re.I))
        except Exception:
            continue

    cand = pick_careers_from_sitemap(all_pages, company_host)
    if diag is not None:
        diag["sitemap"] = f"{fetched} sitemap(s), {len(all_pages)} url(s), pick={cand}"
    if not cand:
        return None
    final, reason = _fetch_and_validate(cand, company_host, catch_all=False)
    if diag is not None and reason:
        diag["sitemap"] += f" rejected:{reason}"
    return final
