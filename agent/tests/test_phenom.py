"""Phenom handler (2026-11-11). No network: request/response shapes are
copied from the live sites checked in Chrome (Adobe, Advance Auto Parts,
Chewy, Acadia, TJX, United, Humana, PNC, Ecolab, Exxon Mobil).

Run:  python -m pytest tests/test_phenom.py -q
"""
import contextlib
import json
from unittest import mock

import pytest
import requests

from agent import ats_api, ats_detector
from agent import platforms as P


# ── Fixtures shaped like the live responses ──────────────────────────────────

ECOLAB_HEAD = (
    '<script>var phApp = phApp || {"widgetApiEndpoint":"https://jobs.ecolab.com/widgets",'
    '"country":"global","deviceType":"desktop","locale":"en_global","absUrl":true,'
    '"refNum":"EIYEIEUS","cdnUrl":"https://cdn.phenompeople.com/CareerConnectResources",'
    '"baseUrl":"https://jobs.ecolab.com/global/en/","baseDomain":"https://jobs.ecolab.com",'
    '"pageName":"search-results","siteType":"external","pageId":"page20"};</script>'
)
PHENOM_PAGE = (
    '<html><head><title>Search results</title>'
    '<link rel="stylesheet" href="https://cdn.phenompeople.com/CareerConnectResources/common/js/'
    'globalplatform/1781270809227_globalstyles.css">'
    '<link rel="icon" href="https://cdn.phenompeople.com/CareerConnectResources/EIYEIEUS/en_global/'
    'desktop/assets/images/favicon.ico">' + ECOLAB_HEAD + '</head><body>Jobs</body></html>'
)
ADOBE_CFG = {"widgetApiEndpoint": "https://careers.adobe.com/widgets", "country": "us",
             "locale": "en_us", "siteType": "external", "baseUrl": "https://careers.adobe.com/us/en/"}


def _job(i, state="Florida", **kw):
    j = {"jobId": f"R-{i:07d}", "title": f"Store Manager {i}", "location": f"Miami, {state}",
         "city": "Miami", "state": state, "country": "United States of America",
         "category": "Field Sales and Service", "postedDate": "2026-10-18T00:00:00.000+0000",
         "descriptionTeaser": "Manage a store team, keep stock right and look after customers. " * 4,
         "jobSeqNo": f"ADAUUSR{i}EXTERNALENUS"}
    j.update(kw)
    return j


class FakeBoard:
    """Answers POST /widgets like Phenom does: from+size past 9,999 gives
    nothing, size is capped at 500, selected_fields filters, counts=true
    adds aggregations for the fields in all_fields. `shuffle` reproduces the
    unstable order seen when paging big searches."""

    def __init__(self, jobs, shuffle=False):
        self.jobs = jobs
        self.shuffle = shuffle
        self.bodies = []

    def __call__(self, url, json=None, headers=None, timeout=None):
        body = json
        self.bodies.append(body)
        resp = mock.Mock(status_code=200)
        resp.raise_for_status = mock.Mock()
        if body.get("ddoKey") == "jobDetail":
            resp.json.return_value = {"jobDetail": {"status": 200, "data": {
                "job": {"description": "<p><b>The Opportunity</b></p><p>" + "Long text. " * 40 + "</p>"}}}}
            return resp
        sel = body.get("selected_fields") or {}
        hits = [j for j in self.jobs if all(j.get(f) in v for f, v in sel.items())]
        start, size = body["from"], min(body["size"], 500)
        if self.shuffle:
            # Every call sees a different order, like the live API.
            import random
            hits = hits[:]
            random.Random(len(self.bodies)).shuffle(hits)
        if start + size > 9999:
            page, total = [], 0
        else:
            page, total = hits[start:start + size], len(hits)
        data = {"jobs": page}
        if body.get("counts"):
            aggs = []
            for f in body.get("all_fields") or []:
                vals = {}
                for j in hits:
                    if j.get(f):
                        vals[j[f]] = vals.get(j[f], 0) + 1
                aggs.append({"field": f, "value": vals})
            data["aggregations"] = aggs
        resp.json.return_value = {"refineSearch": {"status": 200, "hits": len(page),
                                                   "totalHits": total, "data": data}}
        return resp


def _no_page(*a, **kw):
    raise requests.ConnectionError("no page in tests")


def _fetch(board, token="jobs.advanceautoparts.com|us/en", **kw):
    with mock.patch.object(ats_api.requests, "post", side_effect=board), \
         mock.patch.object(ats_api.requests, "get", side_effect=_no_page):
        return ats_api._fetch_phenom(token, **kw)


# ── Job links ────────────────────────────────────────────────────────────────

def test_job_url_uses_jobUrl_when_the_site_sends_it():
    j = {"jobId": "R170391", "title": "x",
         "jobUrl": "https://careers.adobe.com/us/en/job/R170391/Delivery-Manager-Professional-Services-Consulting"}
    assert ats_api._phenom_job_url("https://careers.adobe.com/us/en/", j) == j["jobUrl"]


@pytest.mark.parametrize("job_id,title,expected", [
    # Chewy: en dash and spaces collapse to one hyphen (checked against the page's own link).
    ("R30723", "Functional Developer II – Oracle ERP Finance",
     "https://careers.chewy.com/us/en/job/R30723/Functional-Developer-II-Oracle-ERP-Finance"),
    ("R29637", "Technical Program Manager, HR Service Delivery Optimization",
     "https://careers.chewy.com/us/en/job/R29637/Technical-Program-Manager-HR-Service-Delivery-Optimization"),
    # United: " - " becomes one hyphen.
    ("PDX00000367", "Facilities Maintenance Technician - Line",
     "https://careers.chewy.com/us/en/job/PDX00000367/Facilities-Maintenance-Technician-Line"),
    # Humana: "Sales- Carbon"
    ("R-436428", "Medicare Field Sales- Carbon",
     "https://careers.chewy.com/us/en/job/R-436428/Medicare-Field-Sales-Carbon"),
])
def test_job_url_built_like_the_site_builds_it(job_id, title, expected):
    assert ats_api._phenom_job_url("https://careers.chewy.com/us/en/", {"jobId": job_id, "title": title}) == expected


def test_job_url_global_locale_and_missing_slash():
    j = {"jobId": "R2329547", "title": "Merchandise Associate"}
    assert (ats_api._phenom_job_url("https://jobs.tjx.com/global/en", j)
            == "https://jobs.tjx.com/global/en/job/R2329547/Merchandise-Associate")


# ── Fields ───────────────────────────────────────────────────────────────────

def test_location_fallbacks_humana_remote_jobs():
    assert ats_api._phenom_location({"location": "", "city": "", "state": "", "isRemote": "Yes"}) == "Remote"
    assert ats_api._phenom_location({"location": "", "cityStateCountry": "",
                                     "city": "Boynton", "state": "Florida",
                                     "country": "United States of America"}) == \
        "Boynton, Florida, United States of America"
    assert ats_api._phenom_location({"multi_location": ["Boynton, Florida"]}) == "Boynton, Florida"


def test_small_board_maps_fields_and_uses_teaser_without_detail_calls():
    board = FakeBoard([_job(i) for i in range(268)])
    jobs = _fetch(board, token="careers.adobe.com|us/en")
    assert len(jobs) == 268
    assert len(board.bodies) == 1                       # 268 fits in one 500-job call
    j = jobs[0]
    assert j["title"] == "Store Manager 0"
    assert j["location"] == "Miami, Florida"
    assert j["department"] == "Field Sales and Service"
    assert j["posted_at"] == "2026-10-18"
    assert j["apply_url"] == "https://careers.adobe.com/us/en/job/R-0000000/Store-Manager-0"
    assert len(j["description_snippet"]) >= 100
    assert all(b.get("ddoKey") == "refineSearch" for b in board.bodies)


def test_request_body_matches_what_the_site_sends():
    board = FakeBoard([_job(1)])
    _fetch(board, token="jobs.tjx.com|global/en")
    b = board.bodies[0]
    # Without the page, lang/country come from the token's path.
    assert b["lang"] == "en_global" and b["country"] == "global"
    assert b["siteType"] == "external" and b["pageName"] == "search-results"
    assert b["ddoKey"] == "refineSearch" and b["from"] == 0 and b["size"] == 500
    assert b["jobs"] is True and b["selected_fields"] == {}


def test_config_read_from_the_page_when_available():
    page = mock.Mock(status_code=200, text=PHENOM_PAGE)
    board = FakeBoard([_job(1)])
    with mock.patch.object(ats_api.requests, "get", return_value=page) as g, \
         mock.patch.object(ats_api.requests, "post", side_effect=board) as p:
        jobs = ats_api._fetch_phenom("jobs.ecolab.com|global/en")
    assert g.call_args[0][0] == "https://jobs.ecolab.com/global/en/search-results"
    assert p.call_args[0][0] == "https://jobs.ecolab.com/widgets"
    assert jobs[0]["apply_url"].startswith("https://jobs.ecolab.com/global/en/job/")


# ── Paging limits ────────────────────────────────────────────────────────────

def test_never_asks_past_the_9999_window():
    # One state, nothing to split on, 12,000 jobs: page up to the window only.
    board = FakeBoard([_job(i, state="Texas", category="A", type="Full time",
                            country="US", city="Houston") for i in range(12000)])
    jobs = _fetch(board, cap=10 ** 6)
    assert all(b["from"] + b["size"] <= 9999 for b in board.bodies)
    assert len(jobs) == 9999


def test_big_board_split_by_state_gets_every_job():
    # Advance Auto: 16,284 jobs, more than one search can page through.
    states = ["Florida", "Georgia", "Ohio", "Texas", "Virginia"]
    jobs_in = [_job(i, state=states[i % 5], city=f"City{i % 300}", type=["Full time", "Part time"][i % 2])
               for i in range(16284)]
    board = FakeBoard(jobs_in)
    jobs = _fetch(board, cap=10 ** 6)
    assert len(jobs) == 16284
    assert len({j["apply_url"] for j in jobs}) == 16284
    assert any(b["selected_fields"].get("state") for b in board.bodies)
    assert all(b["from"] + b["size"] <= 9999 for b in board.bodies)


def test_unstable_order_is_beaten_by_splitting_into_one_call_parts():
    # Paging 1,925 Florida jobs with a shifting order lost ~5% live. Split
    # by type and city into parts of <= 500, every job comes back.
    jobs_in = [_job(i, city=f"City{i % 40}", type=["Full time", "Part time"][i % 2]) for i in range(1925)]
    jobs = _fetch(FakeBoard(jobs_in, shuffle=True), cap=10 ** 6)
    assert len(jobs) == 1925


def test_unsplittable_search_with_unstable_order_uses_extra_passes():
    jobs_in = [_job(i, city="Miami", type="Full time", category="A", country="US") for i in range(1200)]
    board = FakeBoard(jobs_in, shuffle=True)
    jobs = _fetch(board, cap=10 ** 6)
    # 3 passes over a shuffled 1,200: nearly everything, and more than one pass was made.
    assert len(jobs) >= 1150
    assert len(board.bodies) > 3


def _advance_auto_board():
    states = [f"S{n}" for n in range(40)]
    return FakeBoard([_job(i, state=states[i % 40]) for i in range(16284)])


def _nightly(board, **patches):
    """fetch_jobs as the nightly run calls it; `patches` override ats_api constants."""
    with mock.patch.object(ats_api.requests, "post", side_effect=board), \
         mock.patch.object(ats_api.requests, "get", side_effect=_no_page), \
         (mock.patch.multiple(ats_api, **patches) if patches else contextlib.nullcontext()):
        diag = {}
        jobs = ats_api.fetch_jobs("phenom", "jobs.advanceautoparts.com|us/en", diag=diag)
    return jobs, diag


def test_nightly_keeps_every_job_on_a_big_phenom_board():
    # Before 2026-11-11 the nightly run kept 5,000 of Advance Auto's 16,284.
    jobs, diag = _nightly(_advance_auto_board())
    assert len(jobs) == 16284
    assert "truncated" not in diag


def test_phenom_cap_still_applies():
    jobs, diag = _nightly(_advance_auto_board(), PHENOM_MAX_JOBS=7000)
    assert len(jobs) == 7000
    assert diag["truncated"] == "hit PHENOM_MAX_JOBS=7000"


def test_time_budget_keeps_what_was_fetched():
    # A slow site: the 120s budget runs out partway; the jobs so far are kept.
    clock = {"t": 0.0}

    def slow_board(*a, **kw):
        clock["t"] += 10.0          # every widgets call "takes" 10s
        return board(*a, **kw)

    board = _advance_auto_board()
    with mock.patch.object(ats_api.time, "monotonic", side_effect=lambda: clock["t"]):
        jobs, diag = _nightly(slow_board)
    assert 0 < len(jobs) < 16284
    assert "120s" in diag["truncated"]


def test_other_platforms_keep_the_5000_cap():
    assert ats_api._job_cap("phenom") == ats_api.PHENOM_MAX_JOBS == 25000
    for ats in ("greenhouse", "workday", "lever", "smartrecruiters"):
        assert ats_api._job_cap(ats) == ats_api.MAX_JOBS_PER_COMPANY == 5000


def test_page_size_is_capped_at_500():
    board = FakeBoard([_job(i) for i in range(50)])
    _fetch(board, page_size=1000)
    assert board.bodies[0]["size"] == 500


def test_fetch_jobs_dispatches_and_records_errors():
    with mock.patch.object(ats_api.requests, "get", side_effect=_no_page), \
         mock.patch.object(ats_api.requests, "post", side_effect=requests.HTTPError("403")):
        diag = {}
        assert ats_api.fetch_jobs("phenom", "careers.adobe.com|us/en", diag=diag) == []
    assert "HTTPError" in diag["fetch_error"]


def test_detail_call_returns_full_description():
    board = FakeBoard([])
    with mock.patch.object(ats_api.requests, "post", side_effect=board):
        text = ats_api.detail_phenom(ADOBE_CFG, "R170391")
    assert text.startswith("The Opportunity")
    assert board.bodies[0]["ddoKey"] == "jobDetail" and board.bodies[0]["jobId"] == "R170391"
    assert board.bodies[0]["pageName"] == "job"


# ── Detection ────────────────────────────────────────────────────────────────

def test_parse_phenom_config_and_token():
    cfg = P.parse_phenom_config(PHENOM_PAGE)
    assert cfg["widgetApiEndpoint"] == "https://jobs.ecolab.com/widgets"
    assert cfg["locale"] == "en_global" and cfg["country"] == "global"
    assert P.phenom_token(cfg) == "jobs.ecolab.com|global/en"
    assert P.parse_phenom_config("<html>no phenom here</html>") is None


def test_parse_phenom_config_json_escaped():
    escaped = ECOLAB_HEAD.replace("/", "\\/")
    assert P.phenom_token(P.parse_phenom_config(escaped)) == "jobs.ecolab.com|global/en"


def test_phenom_page_detected_not_its_css_file():
    # Before: careers_url = cdn.phenompeople.com/...globalstyles.css
    r = ats_detector._extract_ats_from_html(PHENOM_PAGE, "https://jobs.ecolab.com/global/en/home")
    assert (r.ats, r.token, r.can_api) == ("phenom", "jobs.ecolab.com|global/en", True)
    assert r.careers_url == "https://jobs.ecolab.com/global/en/search-results"


def test_phenom_wins_over_workday_apply_links_on_the_page():
    # PNC's Phenom page links each job's Apply button to Workday.
    html = PHENOM_PAGE.replace("<body>", '<body><a href="https://pnc.wd5.myworkdayjobs.com/External/job/x/apply">Apply</a>')
    assert ats_detector._extract_ats_from_html(html, "https://careers.pnc.com/").ats == "phenom"


def test_successfactors_page_is_the_careers_url_not_jquery():
    # jobs.exxonmobil.com, attributes in page order.
    html = ('<script src="https://performancemanager4.successfactors.com/verp/vmod_v1/ui/extlib/'
            'jquery_3.5.1/jquery.js"></script>'
            '<link href="//rmkcdn.successfactors.com/0cbb5fdd/1ee17a12-3c24-4e10-ab6e-0.css">'
            '<a href="https://career4.successfactors.com/career">Sign in</a>')
    r = ats_detector._extract_ats_from_html(html, "https://jobs.exxonmobil.com/")
    assert r.ats == "successfactors"
    assert r.careers_url == "https://jobs.exxonmobil.com/"


def test_outbound_platform_link_still_followed():
    html = '<a href="https://bharatpe.darwinbox.in/ms/candidate/careers">Open roles</a>'
    r = ats_detector._extract_ats_from_html(html, "https://bharatpe.com/careers")
    assert r.ats == "darwinbox" and r.careers_url == "https://bharatpe.darwinbox.in/ms/candidate/careers"


@pytest.mark.parametrize("url,is_asset", [
    ("https://cdn.phenompeople.com/CareerConnectResources/common/js/x_globalstyles.css", True),
    ("https://performancemanager4.successfactors.com/verp/vmod_v1/ui/extlib/jquery_3.5.1/jquery.js", True),
    ("https://rmkcdn.successfactors.com/0cbb5fdd/c7bfa6d3.ico", True),
    ("https://cdn.phenompeople.com/CareerConnectResources/EIYEIEUS", True),
    ("https://career4.successfactors.com/career", False),
    ("https://careers.adobe.com/us/en/search-results", False),
])
def test_static_asset_urls(url, is_asset):
    assert P.is_static_asset_url(url) is is_asset


ADOBE_PAGE = PHENOM_PAGE.replace("jobs.ecolab.com/global/en", "careers.adobe.com/us/en") \
                         .replace("jobs.ecolab.com/widgets", "careers.adobe.com/widgets") \
                         .replace("en_global", "en_us").replace('"country":"global"', '"country":"us"')


def _adobe_get(careers_redirects_to_phenom: bool):
    def fake_get(url, timeout=10):
        r = mock.Mock(status_code=404, text="", url=url, headers={"content-type": "text/html"})
        if url.rstrip("/") in ("https://adobe.com", "https://www.adobe.com"):
            r.status_code, r.text = 200, "<html><title>Adobe</title><a href='/careers'>Careers</a></html>"
        elif url == "https://adobe.com/careers" and careers_redirects_to_phenom:
            r.status_code, r.text, r.url = 200, ADOBE_PAGE, "https://careers.adobe.com/us/en"
        elif url == "https://adobe.com/careers":
            # Live: a marketing page that only links to careers.adobe.com.
            r.status_code, r.url = 200, "https://www.adobe.com/careers.html"
            r.text = ("<html><title>Careers at Adobe</title><h1>Careers</h1>"
                      "<a href='https://careers.adobe.com/us/en/teams'>Teams</a> Find jobs</html>")
        elif url.startswith("https://careers.adobe.com"):
            r.status_code, r.text, r.url = 200, ADOBE_PAGE, "https://careers.adobe.com/us/en"
        return r
    return fake_get


@pytest.mark.parametrize("redirects", [True, False])
def test_detect_ats_adobe_finds_phenom_not_a_css_file(redirects):
    """detect_ats('Adobe', 'adobe.com'). Live, /careers is a marketing page
    (adobe.com/careers.html) and the jobs are on careers.adobe.com, so the
    careers. subdomain guess has to be scanned too."""
    with mock.patch.object(ats_detector, "_probe_known_apis_parallel", return_value=None), \
         mock.patch.object(ats_detector, "_get", side_effect=_adobe_get(redirects)):
        diag = {}
        r = ats_detector.detect_ats("Adobe", "adobe.com", diag=diag)
    assert r.ats == "phenom" and r.token == "careers.adobe.com|us/en" and r.can_api
    assert r.careers_url == "https://careers.adobe.com/us/en/search-results"
    if not redirects:
        assert diag["detected_via"] == "career_path_guess+subdomain_scan"
