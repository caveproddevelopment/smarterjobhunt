"""Tests for the 2026-10-15 description changes (no internet).

  - nightly scrape: no per-job detail calls, 5,000-job cap, paging budget
  - ats_api.detail_for_url: apply_url -> platform API
  - description_fetch: JSON-LD / content extraction, API -> page -> headless render
  - run_description_backfill: host interleaving

Run:  python -m pytest tests -q
"""
import asyncio
import threading
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
STATIC_PAGE = f"""<html><body><main><h1>Plant Engineer</h1><p>{LONG}</p></main></body></html>"""


@pytest.fixture(scope="module")
def local_site():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = {"/js-job": JS_PAGE, "/static-job": STATIC_PAGE}.get(self.path)
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
            return no_render, rendered, missing
        finally:
            await r.close()

    no_render, rendered, missing = asyncio.run(go())
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
