"""Browser-level tests against local fixture sites (no internet).

A tiny HTTP server plays two hosts — a company site (acme.test) and a
Darwinbox-style hiring platform (agro.darwinbox.in) — and Chromium is
pointed at it with --host-resolver-rules. Covers: iframe hand-off to a
platform, JSON capture from a JS job board, "Apply Now" cards, a 404 page
served as 200, a 1,500-anchor page, and the full orchestrator fallback chain
(bad guessed careers URL -> homepage discovery via a Hindi "कैरियर" link).

Run:  python -m pytest tests -q
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

pw = pytest.importorskip("playwright.async_api")

from agent import async_career_scraper as S
from agent import async_ingestion_orchestrator as O
from agent import async_browser_pool as BP
from agent.ats_detector import ATSResult

DBX_JSON = {"status": 1, "message": {"jobs": [
    {"id": "j-101", "title": "Area Sales Manager", "location": "Indore", "department": "Sales", "experience": "3-5"},
    {"id": "j-102", "title": "Agronomist", "location": "Pune", "department": "Agri", "experience": "1-3"},
    {"id": "j-103", "title": "Data Analyst", "location": "Bengaluru", "department": "Tech", "experience": "2-4"},
]}}

PAGES = {
    ("acme.test", "/"): """<html><head><title>Acme Industries</title></head><body>
        <nav><a href="/about">About</a><a href="/welcome/job">कैरियर</a><a href="/contact">Contact</a></nav>
        <h1>Welcome to Acme</h1></body></html>""",
    ("acme.test", "/welcome/job"): """<html><head><title>Careers | Acme</title></head><body>
        <h1>Current openings</h1>
        <ul><li><a href="/jobs/plant-engineer-1001">Plant Engineer</a></li>
            <li><a href="/jobs/quality-manager-1002">Quality Manager</a></li></ul></body></html>""",
    ("acme.test", "/careers"): """<html><head><title>Careers at Acme</title></head><body>
        <h1>Join us</h1><p>See our open positions below.</p>
        <iframe src="http://agro.darwinbox.in/ms/candidate/careers" width="800" height="600"></iframe>
        </body></html>""",
    ("acme.test", "/cards"): """<html><head><title>Careers</title></head><body><h1>Open positions</h1>
        <div class="job-card"><h3>Senior Design Engineer</h3><p>Hyderabad</p><a href="/openings/senior-design-engineer">Apply Now</a></div>
        <div class="job-card"><h3>Quality Inspector</h3><p>Hyderabad</p><a href="/openings/quality-inspector">Apply Now</a></div>
        <a href="/about">About</a></body></html>""",
    ("acme.test", "/missing"): """<html><head><title>Page Not Found</title></head><body><h1>Oops</h1>
        <a href="/careers">Careers</a><a href="/">Home</a></body></html>""",
    ("agro.darwinbox.in", "/ms/candidate/careers"): """<html><head><title>Careers</title></head><body>
        <div id="app">Loading…</div>
        <script>
        fetch('/ms/candidateapi/job?page=1').then(r => r.json()).then(d => {
          const app = document.getElementById('app'); app.innerHTML = '';
          for (const j of d.message.jobs) {
            const div = document.createElement('div'); div.className = 'job-row';
            div.textContent = j.title + ' — ' + j.location; div.onclick = () => {};
            app.appendChild(div);
          }
        });
        </script></body></html>""",
}


def _big_page():
    nav = "".join(f'<a href="/section/{i}">Section {i}</a>' for i in range(1500))
    jobs = "".join(f'<li class="job"><a href="/jobs/role-{i}-engineer">Role {i} Engineer</a></li>' for i in range(5))
    return f"<html><head><title>Careers</title></head><body><h1>Careers</h1><ul>{jobs}</ul>{nav}</body></html>"


PAGES[("acme.test", "/big")] = _big_page()


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        path = self.path.split("?")[0]
        if host == "agro.darwinbox.in" and path == "/ms/candidateapi/job":
            body = json.dumps(DBX_JSON).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        page = PAGES.get((host, path))
        if page is None and path.startswith(("/jobs/", "/openings/")):
            page = f"<html><head><title>Job</title></head><body><h1>{path}</h1><p>{'Responsibilities ' * 30}</p></body></html>"
        if page is None:
            self.send_response(404)
            self.end_headers()
            return
        body = page.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server_port():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture
def resolver_args(server_port, monkeypatch):
    rule = (f"--host-resolver-rules=MAP acme.test 127.0.0.1:{server_port}, "
            f"MAP *.darwinbox.in 127.0.0.1:{server_port}")
    monkeypatch.setattr(BP, "_BASE_ARGS", BP._BASE_ARGS + [rule])
    return rule


def _run(coro):
    return asyncio.run(coro)


async def _scrape(url, diag):
    pool = BP.AsyncBrowserPool()
    try:
        b = await pool.get()
        return await S.scrape_careers_page(url, "http://acme.test", browser=b, diag=diag, company_host="acme.test")
    finally:
        await pool.close()


def test_iframe_platform_json_capture(resolver_args):
    diag = {}
    jobs = _run(_scrape("http://acme.test/careers", diag))
    titles = sorted(j["title"] for j in jobs)
    assert titles == ["Agronomist", "Area Sales Manager", "Data Analyst"], diag
    assert diag.get("used_json_capture") is True
    assert any("darwinbox" in u for u in diag.get("platform_urls", []))


def test_apply_now_cards(resolver_args):
    diag = {}
    jobs = _run(_scrape("http://acme.test/cards", diag))
    assert [j["title"] for j in jobs] == ["Senior Design Engineer", "Quality Inspector"], diag
    # Since 2026-10-15 the nightly scrape doesn't open each job page; the
    # description backfill does that afterwards (tests/test_descriptions.py).
    assert all(j["description_snippet"] == "" for j in jobs)
    assert diag.get("links_before_descriptions") == 2


def test_404_served_as_200_is_rejected(resolver_args):
    diag = {}
    jobs = _run(_scrape("http://acme.test/missing", diag))
    assert jobs == [] and diag["outcome"] == "invalid_page" and diag["page_invalid"] == "not_found_page"


def test_big_page_is_fast(resolver_args):
    import time
    diag = {}
    t0 = time.monotonic()
    jobs = _run(_scrape("http://acme.test/big", diag))
    assert len(jobs) == 5, diag
    assert time.monotonic() - t0 < 30


class _Source:
    def __init__(self, companies):
        self.c = companies

    def load(self):
        return self.c


class _Sink:
    def __init__(self):
        self.rows = []

    def write(self, rows):
        self.rows.extend(rows)


def _company(name, careers_url=""):
    return {"company_name": name, "website": "http://acme.test", "funding_round": "", "funding_amount": "",
            "funding_date": "", "careers_url": careers_url}


def test_orchestrator_bad_guess_falls_back_to_discovery(resolver_args, monkeypatch):
    # detect_ats "guessed" a 404-served-as-200 page; the orchestrator must
    # reject it and find the real careers page via the homepage (Hindi link).
    monkeypatch.setattr(O, "detect_ats", lambda name, website, diag:
                        ATSResult("unknown", None, False, careers_url="http://acme.test/missing"))
    sink, results = _Sink(), []
    summary = _run(O.run(_Source([_company("Acme")]), sink, max_workers=1,
                         progress_callback=lambda *a: None, result_callback=results.extend))
    assert sorted(r["job_title"] for r in sink.rows) == ["Plant Engineer", "Quality Manager"], results
    assert results[0]["stage"] == "ok_career_scrape"
    assert "playwright_homepage_scan" in results[0]["detail"]


def test_orchestrator_careers_url_override(resolver_args, monkeypatch):
    called = []
    monkeypatch.setattr(O, "detect_ats", lambda *a: called.append(1) or ATSResult("unknown", None, False))
    sink, results = _Sink(), []
    _run(O.run(_Source([_company("Acme", careers_url="http://acme.test/careers")]), sink, max_workers=1,
               progress_callback=lambda *a: None, result_callback=results.extend))
    assert len(sink.rows) == 3, results
    assert not called, "detect_ats should not run when the override already produced jobs"
    assert "careers_url_override" in results[0]["detail"]
