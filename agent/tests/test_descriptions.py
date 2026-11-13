"""Tests for the 2026-10-15 description changes (no internet).

  - nightly scrape: no per-job detail calls, 5,000-job cap, paging budget
  - ats_api.detail_for_url: apply_url -> platform API
  - description_fetch: JSON-LD / content extraction, API -> page -> headless render
  - run_description_backfill: host interleaving

Run:  python -m pytest tests -q
"""
import asyncio
import threading
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

import pytest

from agent import ats_api
from agent import async_career_scraper as S
from agent import description_fetch as DF
import run_description_backfill as BF
from tests.test_units import _Resp


# ── Part 1: nightly scrape ───────────────────────────────────────────────────

def _workday_pages(n_total, page_size=20):
    pages = []
    for start in range(0, n_total, page_size):
        pages.append(_Resp({"total": n_total if start == 0 else 0, "jobPostings": [
            {"title": f"Job {i}", "externalPath": f"/job/X/Job-{i}_R{i}", "locationsText": "X"}
            for i in range(start, min(n_total, start + page_size))]}))
    return pages


def test_nightly_workday_makes_no_detail_calls():
    with mock.patch.object(ats_api.requests, "post", side_effect=_workday_pages(45)), \
         mock.patch.object(ats_api.requests, "get") as g:
        jobs = ats_api.fetch_jobs("workday", "acme.wd5.myworkdayjobs.com|acme|Careers")
    assert len(jobs) == 45
    g.assert_not_called()
    assert all(j["description_snippet"] == "" for j in jobs)


def test_nightly_smartrecruiters_makes_no_detail_calls():
    listing = _Resp({"totalFound": 2, "content": [{"id": "111", "name": "A"}, {"id": "222", "name": "B"}]})
    with mock.patch.object(ats_api.requests, "get", return_value=listing) as g:
        jobs = ats_api.fetch_jobs("smartrecruiters", "Acme")
    assert len(jobs) == 2 and g.call_count == 1


def test_detail_calls_still_available_when_asked():
    listing = _Resp({"totalFound": 1, "content": [{"id": "111", "name": "A"}]})
    detail = _Resp({"jobAd": {"sections": {"jobDescription": {"text": "<p>" + "Build things. " * 20 + "</p>"}}}})
    with mock.patch.object(ats_api.requests, "get", side_effect=[listing, detail]):
        jobs = ats_api.fetch_jobs("smartrecruiters", "Acme", fetch_details=True)
    assert jobs[0]["description_snippet"].startswith("Build things.")


def test_list_endpoint_descriptions_are_kept():
    gh = _Resp({"jobs": [{"title": "Eng", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                          "content": "&lt;p&gt;Great job&lt;/p&gt;"}]})
    with mock.patch.object(ats_api.requests, "get", return_value=gh):
        jobs = ats_api.fetch_jobs("greenhouse", "acme")
    assert jobs[0]["description_snippet"] == "Great job"   # escaped HTML is cleaned too


def test_cap_is_5000():
    assert ats_api.MAX_JOBS_PER_COMPANY == 5000
    with mock.patch.object(ats_api.requests, "post", side_effect=_workday_pages(5100)):
        diag = {}
        jobs = ats_api.fetch_jobs("workday", "acme.wd5.myworkdayjobs.com|acme|Careers", diag=diag)
    assert len(jobs) == 5000
    assert "MAX_JOBS_PER_COMPANY" in diag.get("truncated", "")


def test_paging_budget_keeps_partial_results(monkeypatch):
    monkeypatch.setattr(ats_api, "LIST_BUDGET_SECONDS", -1)   # already expired after page 1
    with mock.patch.object(ats_api.requests, "post", side_effect=_workday_pages(100)):
        diag = {}
        jobs = ats_api.fetch_jobs("workday", "acme.wd5.myworkdayjobs.com|acme|Careers", diag=diag)
    assert len(jobs) == 20
    assert "paging stopped" in diag["truncated"]


def test_scraper_no_longer_fetches_job_pages_by_default():
    assert S.SCRAPE_FETCHES_DESCRIPTIONS is False


# ── Part 2: apply_url -> platform API ────────────────────────────────────────

@pytest.mark.parametrize("url,source", [
    ("https://jpmc.wd5.myworkdayjobs.com/en-US/CorporateCareers/job/New-York/Analyst_R123", "workday"),
    ("https://jpmc.wd5.myworkdayjobs.com/CorporateCareers/job/New-York/Analyst_R123", "workday"),
    ("https://wd3.myworkdaysite.com/recruiting/acme/External/job/Pune/Eng_R9", "workday"),
    ("https://jobs.smartrecruiters.com/Freshworks/743999999999999-senior-engineer", "smartrecruiters"),
    ("https://iabiiz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/12345", "oracle"),
    ("https://apply.workable.com/bharatx/j/AB12CD/", "workable"),
    ("https://boards.greenhouse.io/acme/jobs/4012345", "greenhouse"),
    ("https://job-boards.eu.greenhouse.io/groww/jobs/4012345", "greenhouse"),
    ("https://jobs.lever.co/acme/0b5d6c2e-1234-4abc-9def-0123456789ab", "lever"),
    ("https://jobs.ashbyhq.com/bolna/0b5d6c2e-1234-4abc-9def-0123456789ab", None),
    ("https://careers.acme.com/jobs/123", None),
])
def test_detail_source_for_url(url, source):
    assert ats_api.detail_source_for_url(url) == source


def test_detail_for_url_workday_calls_cxs_api():
    info = _Resp({"jobPostingInfo": {"jobDescription": "<p>" + "Analyse data. " * 20 + "</p>"}})
    with mock.patch.object(ats_api.requests, "get", return_value=info) as g:
        source, text = ats_api.detail_for_url(
            "https://jpmc.wd5.myworkdayjobs.com/en-US/CorporateCareers/job/New-York/Analyst_R123")
    assert source == "workday" and text.startswith("Analyse data.")
    assert g.call_args[0][0] == ("https://jpmc.wd5.myworkdayjobs.com/wday/cxs/jpmc/CorporateCareers"
                                 "/job/New-York/Analyst_R123")


def test_detail_for_url_raises_on_http_error():
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp({}, status=404)):
        with pytest.raises(Exception):
            ats_api.detail_for_url("https://jobs.smartrecruiters.com/Acme/123")


# ── Part 2: page extraction ──────────────────────────────────────────────────

LONG = "We are hiring a plant engineer to run maintenance and quality programs. " * 4


def test_extract_prefers_jsonld():
    html = f"""<html><head><script type="application/ld+json">
      {{"@context": "https://schema.org", "@graph": [{{"@type": "JobPosting", "title": "Eng",
        "description": "&lt;p&gt;{LONG}&lt;/p&gt;"}}]}}</script></head>
      <body><nav>Home About Careers</nav><p>Cookie notice</p></body></html>"""
    assert DF.extract_description(html).startswith("We are hiring")


def test_extract_uses_description_block_over_nav():
    html = f"""<html><body><nav>{'Menu item ' * 50}</nav>
      <div class="job-description"><p>{LONG}</p></div><footer>Footer</footer></body></html>"""
    out = DF.extract_description(html)
    assert out.startswith("We are hiring") and "Menu item" not in out


def test_fetch_description_api_path_no_page_fetch():
    with mock.patch.object(DF.ats_api, "detail_for_url", return_value=("oracle", LONG)), \
         mock.patch.object(DF.requests, "get") as g:
        res = asyncio.run(DF.fetch_description(
            "https://x.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/1", None))
    assert res.ok and res.source == "oracle"
    g.assert_not_called()


def test_fetch_description_429_is_transient():
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp({}, status=429)):
        res = asyncio.run(DF.fetch_description("https://jobs.smartrecruiters.com/Acme/123", None))
    assert not res.ok and res.transient and res.error == "http_429"


def test_fetch_description_404_is_counted():
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp({}, status=404)):
        res = asyncio.run(DF.fetch_description("https://jobs.smartrecruiters.com/Acme/123", None))
    assert not res.ok and not res.transient


# ── Part 2: headless fallback for JavaScript job pages (local server) ────────

JS_PAGE = f"""<html><head><title>Job</title></head><body><div id="app">Loading…</div>
<script>setTimeout(() => {{ document.getElementById('app').innerHTML =
  '<div class="job-description"><p>{LONG}</p></div>'; }}, 200);</script></body></html>"""
# Enough nav text to pass 100 characters, but the job itself loads with JavaScript.
JS_SHELL_PAGE = f"""<html><body><nav>{'Home About Careers Contact Investors Newsroom ' * 3}</nav>
<div id="app">Please enable JavaScript to view this job.</div>
<script>setTimeout(() => {{ document.getElementById('app').innerHTML =
  '<div class="job-description"><p>{LONG}</p></div>'; }}, 200);</script></body></html>"""
STATIC_PAGE = f"""<html><body><main><h1>Plant Engineer</h1><p>{LONG}</p></main></body></html>"""


@pytest.fixture(scope="module")
def local_site():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {"/js-job": JS_PAGE, "/static-job": STATIC_PAGE, "/js-shell": JS_SHELL_PAGE}.get(self.path)
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write((body or "<html><body>Not found</body></html>").encode())

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_static_page_needs_no_browser(local_site):
    res = asyncio.run(DF.fetch_description(local_site + "/static-job", None))
    assert res.ok and res.source == "page" and res.text.startswith("Plant Engineer")


def test_js_page_is_rendered_in_headless_browser(local_site):
    pytest.importorskip("playwright.async_api")

    async def go():
        r = DF.Renderer(max_pages=1)
        try:
            no_render = await DF.fetch_description(local_site + "/js-job", None)
            rendered = await DF.fetch_description(local_site + "/js-job", r)
            missing = await DF.fetch_description(local_site + "/nope", r)
            shell = await DF.fetch_description(local_site + "/js-shell", r)
            return no_render, rendered, missing, shell
        finally:
            await r.close()

    no_render, rendered, missing, shell = asyncio.run(go())
    assert shell.ok and shell.source == "page_rendered" and shell.text.startswith("We are hiring")
    assert not no_render.ok and no_render.error == "too_short"
    assert rendered.ok and rendered.source == "page_rendered" and rendered.text.startswith("We are hiring")
    assert not missing.ok and missing.error == "http_404"


# ── Part 2: scheduling ───────────────────────────────────────────────────────

def test_interleave_by_host_round_robins():
    links = ([(1, f"https://a.example.com/j/{i}", 1) for i in range(3)]
             + [(2, f"https://b.example.com/j/{i}", 1) for i in range(2)]
             + [(3, "https://jobs.smartrecruiters.com/X/1", 1)])
    hosts = [BF.host_key(u) for _, u, _ in BF.interleave_by_host(links)]
    assert hosts[:3] == ["a.example.com", "b.example.com", "api.smartrecruiters.com"]
    assert sorted(hosts) == sorted(BF.host_key(u) for _, u, _ in links)


def test_jsonld_entity_escaped_block():
    import html as h
    block = h.escape('{"@type": "JobPosting", "description": "' + LONG + '"}', quote=True)
    html = f'<html><head><script type="application/ld+json">{block}</script></head><body></body></html>'
    assert DF.jobposting_description(html).startswith("We are hiring")


def test_api_without_text_falls_through_to_page():
    page = f"<html><body><main><p>{LONG}</p></main>{'<p>Footer text here.</p>' * 30}</body></html>"
    with mock.patch.object(DF.ats_api, "detail_for_url", return_value=("workday", "")), \
         mock.patch.object(DF, "fetch_page_html", return_value=(page, None)):
        res = asyncio.run(DF.fetch_description("https://acme.wd5.myworkdayjobs.com/C/job/X/Y_R1", None))
    assert res.ok and res.source == "page"


def test_with_descriptions_flag_reaches_fetch_jobs():
    from agent import async_ingestion_orchestrator as O
    import inspect
    assert "fetch_descriptions" in inspect.signature(O.run).parameters
    assert inspect.signature(O.run).parameters["fetch_descriptions"].default is False


# ── #job- listing-anchor links (2026-11-13) ──────────────────────────────────

GEM_URL = "https://jobs.gem.com/cartwheel-1#job-T2F0c0pvYlBvc3Q6NzQ4MDMyOQ%3D%3D"
UKG_BOARD = "https://recruiting.ultipro.com/YAS1000YAAMI/JobBoard/79c5e373-83ab-4894-be19-ed78fff999d4"
UKG_ID = "34169ce2-4eb0-425e-a01d-0c33d6da7d64"
UKG_URL = f"{UKG_BOARD}#job-{UKG_ID}"
DOVER_ID = "aa378aa1-79f3-4995-8667-b78a61c12b11"
DOVER_URL = f"https://jobs.dover.com/Dover/733c3162-cbbd-6558-9866-1d6b8561f8b9?src=app#job-{DOVER_ID}"
GEM_HTML = "<p>" + "Own the robotics fleet roadmap. " * 8 + "</p>"


@pytest.fixture
def gem_cache():
    ats_api._gem_boards.clear()
    yield
    ats_api._gem_boards.clear()


@pytest.mark.parametrize("url, source", [
    (GEM_URL, "gem"),
    ("https://jobs.gem.com/cartwheel-1/#job-abc", "gem"),
    ("https://jobs.gem.com/cartwheel-1", None),                       # the listing page itself
    (DOVER_URL, "dover"),
    ("https://jobs.dover.com/Dover#job-aa378aa1-79f3-4995-8667-b78a61c12b11", "dover"),
    ("https://jobs.dover.com/Dover/aa378aa1-79f3-4995-8667-b78a61c12b11", None),   # a real job page
    (UKG_URL, "ukg"),
    ("https://recruiting2.ultipro.com/ABC1000ABC/JobBoard/79c5e373-83ab-4894-be19-ed78fff999d4#job-x", "ukg"),
    ("https://mywsc.rec.pro.ukg.net/WEI1500WEIN/JobBoard/60a1b2c3-0000-4000-8000-000000000001/#job-x", "ukg"),
    ("https://recruiting.ultipro.com/YAS1000YAAMI/JobBoard/79c5e373-83ab-4894-be19-ed78fff999d4", None),
    ("https://acme.example.com/careers#job-7", None),
])
def test_anchor_detail_source(url, source):
    assert ats_api.detail_source_for_url(url) == source


def test_anchor_hosts_come_from_registered_handlers():
    assert ats_api.ANCHOR_HOST_LIKE == ("jobs.gem.com", "recruiting.ultipro.com",
                                        "recruiting2.ultipro.com", "%.rec.pro.ukg.net", "jobs.dover.com")


@pytest.mark.parametrize("post_id", [
    "T2F0c0pvYlBvc3Q6NzQ4MDMyOQ==",   # same global ID we stored
    "7480329",                        # numeric ID
    "OatsJobPost:7480329",            # decoded global ID
])
def test_gem_matches_id_in_any_form(gem_cache, post_id):
    posts = [{"id": "999", "content": "<p>wrong job</p>" * 20},
             {"id": post_id, "title": "Robotics PM", "content": GEM_HTML}]
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(posts)) as g:
        source, text = ats_api.detail_for_url(GEM_URL)
    assert source == "gem" and text.startswith("Own the robotics fleet roadmap.")
    assert g.call_args[0][0] == "https://api.gem.com/job_board/v0/cartwheel-1/job_posts/"


def test_gem_board_list_fetched_once_per_board(gem_cache):
    posts = [{"id": f"{i}", "content": GEM_HTML} for i in range(5)]
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(posts)) as g:
        for i in range(5):
            ats_api.detail_for_url(f"https://jobs.gem.com/acme#job-{i}")
        ats_api.detail_for_url("https://jobs.gem.com/other#job-1")
    assert g.call_count == 2


def test_gem_closed_post_is_too_short_not_page_fetch(gem_cache):
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp([{"id": "1", "content": GEM_HTML}])), \
         mock.patch.object(DF, "fetch_page_html") as page:
        res = asyncio.run(DF.fetch_description(GEM_URL, None))
    assert not res.ok and res.error == "too_short" and res.source == "gem"
    page.assert_not_called()


def test_gem_api_error_is_not_cached_and_is_transient(gem_cache):
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp({}, status=503)):
        res = asyncio.run(DF.fetch_description(GEM_URL, None))
    assert not res.ok and res.transient and res.source == "gem"
    assert ats_api._gem_boards == {}


def test_anchor_link_without_handler_is_no_handler():
    with mock.patch.object(DF, "fetch_page_html") as page:
        res = asyncio.run(DF.fetch_description("https://acme.example.com/careers#job-7", None))
    assert not res.ok and res.error == "no_handler"
    page.assert_not_called()


def test_gem_links_share_one_host_limit():
    assert BF.host_key(GEM_URL) == "api.gem.com"
    assert BF.host_key("https://jobs.gem.com/other#job-1") == "api.gem.com"


def test_build_filters_lets_only_handled_anchor_hosts_through():
    where, params = BF.build_filters({"review_status", "promoted_at"}, None)
    assert params[0] == list(ats_api.ANCHOR_HOST_LIKE)


def _ukg_page(opp: dict) -> str:
    """Shaped like the live OpportunityDetail page (checked 13 Nov 2026)."""
    import json
    return ("<html><body><div id='Successbanner'></div><script>\n$(function () {\n"
            "    var opportunity = new US.Opportunity.CandidateOpportunityDetail("
            + json.dumps(opp) + ", {\"Culture\":\"en-US\"});\n});\n</script></body></html>")


class _HtmlResp:
    def __init__(self, text, status=200):
        self.text, self.status_code, self.headers = text, status, {"content-type": "text/html"}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            e = requests.HTTPError(str(self.status_code))
            e.response = self
            raise e


UKG_DESC = "<p>SUMMARY <br />Under general supervision, design new robotic systems {and} products. </p>" * 3


def test_ukg_reads_description_from_page_json():
    page = _ukg_page({"Id": UKG_ID, "Title": "Mechanical Engineer", "Description": UKG_DESC,
                      "Locations": [{"Address": {"City": "Miamisburg"}}], "OpportunityIsClosed": False})
    with mock.patch.object(ats_api.requests, "get", return_value=_HtmlResp(page)) as g:
        source, text = ats_api.detail_for_url(UKG_URL)
    assert source == "ukg" and text.startswith("SUMMARY") and "{and}" in text
    assert g.call_args[0][0] == f"{UKG_BOARD}/OpportunityDetail?opportunityId={UKG_ID}"


@pytest.mark.parametrize("page", [
    "<html><body>Find Opportunities</body></html>",                                  # unknown / closed ID
    _ukg_page({"Id": UKG_ID, "Description": UKG_DESC, "OpportunityIsClosed": True}),
    _ukg_page({"Id": "11111111-2222-3333-4444-555555555555", "Description": UKG_DESC}),  # another job
])
def test_ukg_closed_or_missing_job_is_too_short(page):
    with mock.patch.object(ats_api.requests, "get", return_value=_HtmlResp(page)), \
         mock.patch.object(DF, "fetch_page_html") as listing_fetch:
        res = asyncio.run(DF.fetch_description(UKG_URL, None))
    assert not res.ok and res.error == "too_short" and res.source == "ukg"
    listing_fetch.assert_not_called()


def test_ukg_rate_limit_is_transient():
    with mock.patch.object(ats_api.requests, "get", return_value=_HtmlResp("", status=429)):
        res = asyncio.run(DF.fetch_description(UKG_URL, None))
    assert not res.ok and res.transient and res.source == "ukg"


def test_ukg_hosts_get_one_request_at_a_time():
    """--per-host 2, but a UKG host never has two fetches in flight."""
    in_flight, peak = Counter(), Counter()

    async def fake(url, renderer):
        h = BF.host_key(url)
        in_flight[h] += 1
        peak[h] = max(peak[h], in_flight[h])
        await asyncio.sleep(0.02)
        in_flight[h] -= 1
        return DF.FetchResult(True, text="x" * 200, source="t")

    class W:
        conn = None
        def success(self, *a): pass
        def failure(self, *a, **k): pass
        def flush(self): pass

    todo = [(1, f"{UKG_BOARD}#job-{i}", 1) for i in range(6)] + \
           [(2, f"https://careers.acme.com/jobs/{i}", 1) for i in range(6)]
    with mock.patch.object(BF, "fetch_description", fake), mock.patch.object(BF, "PER_HOST_DELAY_SECONDS", 0):
        asyncio.run(BF.run_fetches(todo, W(), concurrency=8, per_host=2, max_seconds=60,
                                   render=False, render_pages=1))
    assert peak["recruiting.ultipro.com"] == 1 and peak["careers.acme.com"] == 2


def _dover_jd(**kw):
    """Shaped like /api/v1/jobs/<uuid>/get_job_description (checked 13 Nov 2026)."""
    d = {"id": "239dd6a7-20db-4dc2-9d64-7e2fcd6ec0a2", "job": {"id": DOVER_ID}, "use_dover_jd": False,
         "is_published": True,
         "generated_description": {"about_the_role": None, "job_mandates": None, "qualifications": None,
                                   "about_the_company": None, "additional_information": None, "ai_generated": False},
         "user_facing_description": "## Job Title\n\nStartup Counsel (stale) " * 6,
         "user_provided_description": "<h2>Company Overview</h2><p>" + "Dover is building the marketplace for startup experts. " * 4 + "</p>",
         "external_url": None}
    d.update(kw)
    return d


def test_dover_uses_the_description_the_page_shows():
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(_dover_jd())) as g:
        source, text = ats_api.detail_for_url(DOVER_URL)
    assert source == "dover" and text.startswith("Company Overview") and "Startup Counsel" not in text
    assert g.call_args[0][0] == f"https://jobs.dover.com/api/v1/jobs/{DOVER_ID}/get_job_description"


def test_dover_generated_description_when_page_uses_it():
    jd = _dover_jd(use_dover_jd=True, generated_description={
        "about_the_role": "Lead people operations for a fast-growing startup marketplace. " * 3,
        "qualifications": ["Ten years in HR", "Startup experience"]})
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(jd)):
        _source, text = ats_api.detail_for_url(DOVER_URL)
    assert text.startswith("Lead people operations") and "Startup experience" in text


def test_dover_markdown_fallback():
    jd = _dover_jd(user_provided_description="", user_facing_description="## About\n\n" + "Real role text here. " * 8)
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(jd)):
        _source, text = ats_api.detail_for_url(DOVER_URL)
    assert "Real role text here." in text


@pytest.mark.parametrize("resp", [_Resp({"detail": "Not found."}, status=404), _Resp(_dover_jd(is_published=False))])
def test_dover_closed_job_is_too_short(resp):
    with mock.patch.object(ats_api.requests, "get", return_value=resp), \
         mock.patch.object(DF, "fetch_page_html") as listing_fetch:
        res = asyncio.run(DF.fetch_description(DOVER_URL, None))
    assert not res.ok and res.error == "too_short" and res.source == "dover"
    listing_fetch.assert_not_called()


def test_dover_server_error_is_transient():
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp({}, status=502)):
        res = asyncio.run(DF.fetch_description(DOVER_URL, None))
    assert not res.ok and res.transient and res.source == "dover"
