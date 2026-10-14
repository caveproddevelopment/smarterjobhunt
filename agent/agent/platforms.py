"""
Platforms — shared knowledge about hiring platforms (ATS hosts) and about
pages that must never be accepted as a careers page.

Added 2026-10-13 from the 7 Oct run analysis of 655 Indian companies that
returned 0 jobs (indian_companies_zero_jobs_findings.csv). Three things
live here so ats_detector.py, async_career_scraper.py and the orchestrator
all agree on them:

1. parse_ats_url(url)        -> (ats, token) for every platform we have a
                               JSON API adapter for in ats_api.py.
2. platform_for_url(url)     -> platform name for any known hiring-platform
                               host, API or not (Darwinbox, Keka, PeopleStrong,
                               SenseHQ, ZingHR, ...). Used to follow a careers
                               page that redirects to, iframes, or links out
                               to the real job board.
3. classify_page(...)        -> reason string if a fetched page is NOT a usable
                               careers page (image, 404 served as 200, error
                               route, login page, parked domain, redirect to
                               homepage or to an unrelated site, bot wall),
                               else None.

Everything here is pure (no network) so it can be unit-tested.
"""

import html as _html
import re
from typing import Optional
from urllib.parse import urlparse, unquote

# ─────────────────────────────────────────────────────────────────────────────
# Text normalisation for URL scanning
# ─────────────────────────────────────────────────────────────────────────────

def unescape_for_scan(text: str) -> str:
    """Undo the encodings that hide URLs inside page source: HTML entities
    (&quot; &#34; &amp;), JSON-escaped slashes (\\/ and \\u002F) and \\u0026.
    Without this, URLs embedded in JSON blobs were cut at the entity and
    produced garbage like 'https://opportunities&#34;,&#34;link...' and
    'https://nmyworkdayjobs.com' (both seen in the 7 Oct Railway logs)."""
    if not text:
        return ""
    t = text.replace("\\u002F", "/").replace("\\u002f", "/").replace("\\/", "/")
    t = t.replace("\\u0026", "&").replace("\\u003d", "=").replace("\\u003D", "=")
    t = _html.unescape(t)
    # Literal "\n", "\t" etc. left over from JSON strings glue onto the next
    # word ("\nmyworkdayjobs.com") — turn them into whitespace.
    t = re.sub(r"\\[nrt]", " ", t)
    return t


# ─────────────────────────────────────────────────────────────────────────────
# API-capable ATS URLs
# ─────────────────────────────────────────────────────────────────────────────

# Path segments that are NOT a company's board token.
RESERVED_TOKENS = {
    "greenhouse":      {"embed", "v1", "jobs", "api", "boards", "job_board", "js", "assets", "static", "widget"},
    "lever":           {"jobs", "api", "v0", "postings", "assets", "static", "embed"},
    "ashby":           {"api", "jobs", "embed", "assets", "static", "posting-api"},
    "workable":        {"j", "api", "jobs", "assets", "static", "widget", "oauth", "careers"},
    "smartrecruiters": {"oneclick-ui", "embed", "api", "static", "assets", "widget", "v1", "jobs", "careers"},
    "workday":         {"wday", "cxs", "assets", "static"},
    "recruitee":       {"www", "app", "api", "careers", "static", "assets", "blog", "support", "help"},
}

# (regex, ats) in priority order. Every regex must be run against
# unescape_for_scan() output. Tokens are case-preserving: Ashby board names
# are case-sensitive and can contain dots and URL-encoded spaces
# ("Local%20Kitchens"), which the old [a-z0-9_-]+ pattern cut short
# (7 Oct logs: ashby/The, ashby/Local, ashby/Gray ... all 404).
_ATS_URL_PATTERNS = [
    # Greenhouse embed keeps the token in ?for=
    (re.compile(r"(?:job-)?boards(\.eu)?\.greenhouse\.io/embed/job_board[^\"'\s<>]*?[?&;]for=([A-Za-z0-9_-]+)", re.I), "greenhouse"),
    (re.compile(r"boards-api(\.eu)?\.greenhouse\.io/v1/boards/([A-Za-z0-9_-]+)", re.I), "greenhouse"),
    (re.compile(r"(?:job-)?boards(\.eu)?\.greenhouse\.io/([A-Za-z0-9_-]+)", re.I), "greenhouse"),
    (re.compile(r"api(\.eu)?\.lever\.co/v0/postings/([A-Za-z0-9_.-]+)", re.I), "lever"),
    (re.compile(r"jobs(\.eu)?\.lever\.co/([A-Za-z0-9_.-]+)", re.I), "lever"),
    (re.compile(r"api\.ashbyhq\.com/posting-api/job-board/([A-Za-z0-9_.%-]+)", re.I), "ashby"),
    (re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)", re.I), "ashby"),
    (re.compile(r"apply\.workable\.com/(?:api/v[0-9]/(?:widget/)?accounts/)?([A-Za-z0-9_-]+)", re.I), "workable"),
    (re.compile(r"api\.smartrecruiters\.com/v1/companies/([A-Za-z0-9_-]+)", re.I), "smartrecruiters"),
    (re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I), "smartrecruiters"),
    # Workday: tenant.wdN.myworkdayjobs.com/[locale/]site
    (re.compile(r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[a-z0-9-]+/)?(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)", re.I), "workday"),
    # Workday on myworkdaysite.com: wdN.myworkdaysite.com/[locale/]recruiting/tenant/site
    (re.compile(r"(wd\d+)\.myworkdaysite\.com/(?:[a-z]{2}-[A-Z]{2}/)?recruiting/([a-z0-9-]+)/([A-Za-z0-9_-]+)", re.I), "workday_site"),
    # Oracle Recruiting Cloud candidate experience
    (re.compile(r"([a-z0-9-]+\.fa(?:\.[a-z0-9-]+)?\.oraclecloud\.com)/hcmUI/CandidateExperience/[A-Za-z_-]+/sites/([A-Za-z0-9_]+)", re.I), "oracle"),
    (re.compile(r"([a-z0-9-]+\.fa(?:\.[a-z0-9-]+)?\.oraclecloud\.com)", re.I), "oracle_host"),
    (re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I), "recruitee"),
]

# ATS names ats_api.fetch_jobs() can call.
API_ATS = {
    "greenhouse", "greenhouse_eu", "lever", "lever_eu", "ashby", "workable",
    "smartrecruiters", "workday", "oracle", "recruitee",
}


def _clean_token(tok: str) -> str:
    return (tok or "").strip().strip(".").strip()


def parse_ats_url(text: str) -> Optional[tuple[str, str]]:
    """Find the first API-capable ATS board reference in `text` (a URL or a
    whole page's source) and return (ats, token), else None.

    Token formats:
      greenhouse/greenhouse_eu/lever/lever_eu/ashby/workable/smartrecruiters/recruitee:
          the board slug
      workday:  "<host>|<tenant>|<site>"   e.g. "fractal.wd1.myworkdayjobs.com|fractal|Careers"
      oracle:   "<host>|<siteNumber>"      siteNumber may be "" when only the host is known
    """
    if not text:
        return None
    t = unescape_for_scan(text)
    for rx, ats in _ATS_URL_PATTERNS:
        for m in rx.finditer(t):
            if ats in ("greenhouse", "lever"):
                eu, tok = m.group(1), _clean_token(m.group(2))
                if not tok or tok.lower() in RESERVED_TOKENS[ats]:
                    continue
                return (f"{ats}_eu" if eu else ats), tok
            if ats in ("ashby", "workable", "smartrecruiters"):
                tok = _clean_token(m.group(1))
                if not tok or unquote(tok).lower() in RESERVED_TOKENS[ats]:
                    continue
                return ats, tok
            if ats == "recruitee":
                tok = m.group(1).lower()
                if tok in RESERVED_TOKENS["recruitee"]:
                    continue
                return "recruitee", tok
            if ats == "workday":
                tenant, wd, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
                if site.lower() in RESERVED_TOKENS["workday"] or site.lower() == "job":
                    continue
                return "workday", f"{tenant}.{wd}.myworkdayjobs.com|{tenant}|{site}"
            if ats == "workday_site":
                wd, tenant, site = m.group(1).lower(), m.group(2).lower(), m.group(3)
                return "workday", f"{wd}.myworkdaysite.com|{tenant}|{site}"
            if ats == "oracle":
                return "oracle", f"{m.group(1).lower()}|{m.group(2)}"
            if ats == "oracle_host":
                return "oracle", f"{m.group(1).lower()}|"
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Every known hiring-platform host (API or not)
# ─────────────────────────────────────────────────────────────────────────────

# (host suffix, platform name). Matched against the URL's host by suffix.
PLATFORM_HOSTS = [
    # API adapters exist for these (see ats_api.py)
    ("greenhouse.io", "greenhouse"), ("lever.co", "lever"), ("ashbyhq.com", "ashby"),
    ("workable.com", "workable"), ("smartrecruiters.com", "smartrecruiters"),
    ("myworkdayjobs.com", "workday"), ("myworkdaysite.com", "workday"),
    ("oraclecloud.com", "oracle"), ("recruitee.com", "recruitee"),
    # Browser scrape (+ JSON capture) only
    ("darwinbox.in", "darwinbox"), ("darwinbox.com", "darwinbox"),
    ("keka.com", "keka"), ("peoplestrong.com", "peoplestrong"), ("sensehq.com", "sensehq"),
    ("zinghr.com", "zinghr"), ("kula.ai", "kula"), ("recruiterbox.com", "recruiterbox"),
    ("pyjamahr.com", "pyjamahr"), ("dover.com", "dover"), ("dover.io", "dover"),
    ("successfactors.com", "successfactors"), ("successfactors.eu", "successfactors"),
    ("sapsf.com", "successfactors"), ("sapsf.eu", "successfactors"),
    ("csod.com", "cornerstone"), ("zohorecruit.com", "zoho"), ("zohorecruit.in", "zoho"),
    ("zohorecruit.eu", "zoho"), ("talentrecruit.com", "talentrecruit"), ("workline.hr", "workline"),
    ("turbohire.co", "turbohire"), ("akriviahcm.com", "akrivia"), ("zappyhire.com", "zappyhire"),
    ("freshteam.com", "freshteam"), ("param.ai", "param"), ("skillate.com", "skillate"),
    ("myadrenalin.com", "adrenalin"), ("ripplehire.com", "ripplehire"), ("flexiele.com", "flexiele"),
    ("zwayam.com", "zwayam"), ("qandle.com", "qandle"), ("phenompeople.com", "phenom"),
    ("eightfold.ai", "eightfold"), ("icims.com", "icims"), ("taleo.net", "taleo"),
    ("jobvite.com", "jobvite"), ("teamtailor.com", "teamtailor"), ("breezy.hr", "breezy"),
    ("bamboohr.com", "bamboohr"), ("rippling.com", "rippling"), ("personio.de", "personio"),
    ("personio.com", "personio"), ("ultipro.com", "ultipro"), ("paylocity.com", "paylocity"),
    ("dayforcehcm.com", "dayforce"), ("jazzhr.com", "jazzhr"), ("applytojob.com", "jazzhr"),
    ("hire.trakstar.com", "trakstar"), ("hrmdirect.com", "hrmdirect"), ("pinpointhq.com", "pinpoint"),
    ("jobs.gem.com", "gem"), ("wellfound.com", "wellfound"), ("instahyre.com", "instahyre"),
    ("springrecruit.com", "springrecruit"), ("kenexa.com", "kenexa"), ("brassring.com", "kenexa"),
]

# Hosts that are never a careers page for the company being scraped.
NON_CAREERS_HOSTS = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "tiktok.com", "glassdoor.com", "glassdoor.co.in", "indeed.com",
    "naukri.com", "wikipedia.org", "play.google.com", "apps.apple.com",
)

PARKED_HOSTS = (
    "hugedomains.com", "sedo.com", "sedoparking.com", "dan.com", "afternic.com",
    "parkingcrew.net", "bodis.com", "above.com", "undeveloped.com", "godaddysites.com",
    "domainmarket.com", "buydomains.com", "perfectdomain.com",
)


def host_of(url: str) -> str:
    try:
        u = url if "//" in (url or "") else "https://" + (url or "")
        return (urlparse(u).hostname or "").lower()
    except Exception:
        return ""


def host_matches(host: str, suffixes) -> bool:
    host = (host or "").lower()
    return any(host == s or host.endswith("." + s) for s in suffixes)


def platform_for_url(url: str) -> Optional[str]:
    h = host_of(url)
    if not h:
        return None
    for suffix, name in PLATFORM_HOSTS:
        if h == suffix or h.endswith("." + suffix):
            return name
    return None


_SECOND_LEVEL = {"co", "com", "org", "net", "gov", "ac", "edu", "bank", "nic", "firm",
                 "gen", "ind", "res", "ltd", "plc", "or", "ne", "go"}


def registrable_domain(host: str) -> str:
    """Approximate eTLD+1 without a public-suffix list: handles the forms in
    our company lists (example.com, example.co.in, kotak.bank.in, sjvn.nic.in)."""
    labels = [l for l in (host or "").lower().split(".") if l]
    if labels and labels[0] == "www":
        labels = labels[1:]
    if len(labels) >= 3 and labels[-2] in _SECOND_LEVEL and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def brand_label(host: str) -> str:
    return registrable_domain(host).split(".")[0]


def same_company_site(host_a: str, host_b: str) -> bool:
    """True if two hosts plausibly belong to the same company: same
    registrable domain, or the same brand label (canarabank.com ->
    canarabank.bank.in, bata.in -> bata.com)."""
    if not host_a or not host_b:
        return False
    ra, rb = registrable_domain(host_a), registrable_domain(host_b)
    if ra == rb:
        return True
    ba, bb = brand_label(host_a), brand_label(host_b)
    return len(ba) >= 4 and len(bb) >= 4 and (ba == bb or ba in bb or bb in ba)


# ─────────────────────────────────────────────────────────────────────────────
# Page validation
# ─────────────────────────────────────────────────────────────────────────────

_NON_HTML_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|bmp|ico|pdf|docx?|xlsx?|pptx?|zip|mp4|mp3)$", re.I)
_ERROR_PATH = re.compile(
    r"(^|/)(404(\.html?)?|500|error(s)?|errorpage|error\.aspx|err\.html|pagenotfound|page-not-found|"
    r"not-found|notfound|customerror|exception|lander)(/|$|\.|\?)", re.I)
_ERROR_PATH_ANY = re.compile(r"/(errors?/|customerror/)", re.I)
_LOGIN_PATH = re.compile(r"(^|/)(login|log-in|signin|sign-in|sign_in|account/login|auth/login|sso)(/|$|\?|\.)", re.I)
_AGE_GATE_PATH = re.compile(r"(^|/)age-?gate", re.I)
_NOT_FOUND_TITLE = re.compile(
    r"(\b404\b|page not found|not found|page error|error page|page does not exist|"
    r"page doesn.?t exist|no longer available|something went wrong|oops)", re.I)
_LOGIN_TITLE = re.compile(r"^\s*(log ?in|sign ?in|login page)\b", re.I)
_PARKED_TEXT = re.compile(
    r"(this domain (is|may be) for sale|buy this domain|domain is parked|parked free|"
    r"domain has expired|coming soon|website coming soon|under construction|"
    r"deployment (has been )?paused|site not found|default web site page|"
    r"congratulations.{0,40}(godaddy|hosting))", re.I)
_BOT_WALL = re.compile(
    r"(just a moment|attention required|checking your browser|cf-chl|cf_chl|"
    r"verify you are human|are you a robot|access denied|request rejected|"
    r"perfdrive|shieldsquare|incapsula|captcha)", re.I)
_BOT_HOSTS = ("perfdrive.com", "shieldsquare.com", "captcha-delivery.com")

CAREER_WORDS = re.compile(
    r"(career|job|opening|vacanc|hiring|recruit|position|join (us|our)|work with us|"
    r"apply|opportunit|कैरियर|करियर|नौकरी|भर्ती|रिक्ति)", re.I)


def classify_page(requested_url: str, final_url: str, status: Optional[int],
                  content_type: str = "", title: str = "", heading: str = "",
                  text_sample: str = "", company_host: str = "",
                  require_career_words: bool = True) -> Optional[str]:
    """Return a reason code if this fetched page is NOT a usable careers page,
    else None. All inputs are optional except the URLs; pass what you have.

    reason codes: http_<n> | not_html | parked_domain | bot_wall | error_page |
                  not_found_page | login_page | age_gate | redirected_home |
                  off_site_redirect | no_career_content
    """
    final_url = final_url or requested_url or ""
    fp = urlparse(final_url if "//" in final_url else "https://" + final_url)
    fhost = (fp.hostname or "").lower()
    fpath = fp.path or "/"
    req_host = host_of(requested_url)
    company_host = (company_host or req_host or "").lower()
    on_platform = platform_for_url(final_url) is not None
    text_l = (text_sample or "")[:6000]

    if status is not None and status >= 400:
        return f"http_{status}"
    ct = (content_type or "").lower()
    if (ct and "html" not in ct and "xml" not in ct) or _NON_HTML_EXT.search(fpath):
        return "not_html"
    if host_matches(fhost, PARKED_HOSTS) or fpath.rstrip("/").lower().endswith("/lander") or fpath.lower() == "/lander":
        return "parked_domain"
    if host_matches(fhost, _BOT_HOSTS) or _BOT_WALL.search(title or "") or (
            len(text_l) < 1500 and _BOT_WALL.search(text_l)):
        return "bot_wall"
    if _PARKED_TEXT.search(title or "") or (len(text_l) < 800 and _PARKED_TEXT.search(text_l)):
        return "parked_domain"
    if _ERROR_PATH.search(fpath) or _ERROR_PATH_ANY.search(fpath):
        return "error_page"
    if _NOT_FOUND_TITLE.search(title or "") or _NOT_FOUND_TITLE.search((heading or "")[:120]):
        return "not_found_page"
    if _AGE_GATE_PATH.search(fpath):
        return "age_gate"
    if not on_platform and (_LOGIN_PATH.search(fpath) or _LOGIN_TITLE.search(title or "")):
        return "login_page"

    req_path = urlparse(requested_url if "//" in (requested_url or "") else "https://" + (requested_url or "")).path or "/"
    if (req_path.strip("/") and fpath.strip("/") == "" and not fp.query
            and same_company_site(fhost, req_host)):
        return "redirected_home"
    # Off-site only counts when a *redirect* took us there: a careers link the
    # company itself points at (hul.co.in -> careers.unilever.com) is fine,
    # a /careers guess that bounces to chicagomovingcompany.org is not.
    if (fhost and req_host and fhost != req_host and not on_platform
            and not same_company_site(fhost, req_host)
            and not same_company_site(fhost, company_host)):
        return "off_site_redirect"
    if require_career_words and not on_platform:
        blob = " ".join([title or "", heading or "", text_l, fpath])
        if not CAREER_WORDS.search(blob):
            return "no_career_content"
    return None


def extract_title_and_heading(html: str) -> tuple[str, str]:
    """Cheap <title> and first <h1> extraction from raw HTML (no parser)."""
    if not html:
        return "", ""
    head = html[:200_000]
    t = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
    h = re.search(r"<h1[^>]*>(.*?)</h1>", head, re.I | re.S)
    clean = lambda s: re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
    return clean(t.group(1) if t else ""), clean(h.group(1) if h else "")


def visible_text_sample(html: str, limit: int = 6000) -> str:
    """Rough visible text from raw HTML (scripts/styles stripped), for
    classify_page()'s keyword checks. Not a parser — good enough to look
    for 'page not found' or career words."""
    if not html:
        return ""
    s = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html[:400_000])
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", _html.unescape(s)).strip()
    return s[:limit]
