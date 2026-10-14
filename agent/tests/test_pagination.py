"""Pagination tests against a local fixture site (no internet).

One host (paged.test) serves careers pages with each kind of pager we
handle: numbered links (?page=N), a "Load more" button, a JS "Next ›" button
that is disabled on the last page, an icon-only arrow with aria-label, a
cookie banner that covers the pager until accepted, and a carousel arrow
that must NOT be clicked.

Run:  python -m pytest tests -q
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import pytest

pytest.importorskip("playwright.async_api")

from agent import async_career_scraper as S
from agent import async_browser_pool as BP

TITLES = ["Process Engineer", "Quality Analyst", "Sales Manager", "Plant Supervisor",
          "Data Scientist", "HR Executive", "Finance Associate", "Design Engineer",
          "Maintenance Technician", "Supply Chain Lead", "Product Manager", "Field Officer",
          "Legal Counsel", "Service Engineer", "Marketing Lead"]


def _job_links(prefix, page, n):
    return "".join(
        f'<li class="job"><a href="/jobs/{prefix}-p{page}-{i}">{TITLES[((page - 1) * n + i) % len(TITLES)]} '
        f'{chr(65 + page)}{i}</a></li>' for i in range(n))


def _numbered(page):
    pager = "".join(f'<li><a href="/numbered?page={i}">{i}</a></li>' for i in range(1, 4))
    nxt = f'<li><a href="/numbered?page={page + 1}" aria-label="Next">›</a></li>' if page < 3 else ""
    return f"""<html><head><title>Careers - Open positions</title></head><body>
      <h1>Current openings (page {page})</h1><ul>{_job_links('num', page, 4)}</ul>
      <ul class="pagination">{pager}{nxt}</ul></body></html>"""


def _numbers_only(page):
    # 4 pages, pager is just "1 2 3 4" (no Next/arrow); current page is a <span>.
    items = "".join((f'<span class="current">{i}</span>' if i == page else f'<a href="/numonly?page={i}">{i}</a>')
                    for i in range(1, 5))
    return f"""<html><head><title>Careers</title></head><body><h1>Open jobs</h1>
      <ul>{_job_links('no', page, 2)}</ul><div class="pages">{items}</div></body></html>"""


LOADMORE = """<html><head><title>Careers</title></head><body><h1>Open positions</h1>
<ul id="list"></ul><button id="more" class="btn">Load more jobs</button>
<script>
const all = %s; let shown = 0;
function more() {
  const ul = document.getElementById('list');
  for (const j of all.slice(shown, shown + 5)) {
    const li = document.createElement('li'); li.className = 'job';
    li.innerHTML = '<a href="/jobs/lm-' + j.id + '">' + j.title + '</a>'; ul.appendChild(li);
  }
  shown += 5;
  if (shown >= all.length) document.getElementById('more').style.display = 'none';
}
document.getElementById('more').onclick = () => setTimeout(more, 200);
more();
</script></body></html>""" % json.dumps([{"id": i, "title": f"{TITLES[i % len(TITLES)]} L{i}"} for i in range(13)])

SPA_NEXT = """<html><head><title>Careers</title></head><body><h1>Job openings</h1>
<div id="list"></div>
<div class="pager"><button id="prev">‹ Prev</button><span id="num"></span><button id="next">Next ›</button></div>
<script>
const pages = %s; let p = 0;
function render() {
  document.getElementById('list').innerHTML = pages[p].map(j =>
    '<div class="job-card"><a href="/jobs/spa-' + j.id + '">' + j.title + '</a></div>').join('');
  document.getElementById('num').textContent = (p + 1) + ' / ' + pages.length;
  document.getElementById('next').disabled = (p === pages.length - 1);
}
document.getElementById('next').onclick = () => { if (p < pages.length - 1) { p++; setTimeout(render, 150); } };
render();
</script></body></html>""" % json.dumps([[{"id": f"{pg}-{i}", "title": f"{TITLES[(pg * 3 + i) % len(TITLES)]} S{pg}{i}"}
                                           for i in range(3)] for pg in range(3)])

ARROW = """<html><head><title>Careers</title></head><body><h1>Join our team - open roles</h1>
<div id="list"></div>
<nav class="pagination" aria-label="pagination"><button class="pg-btn" aria-label="Next page" id="arr">
<svg width="10" height="10"><path d="M0 0 L10 5 L0 10"/></svg></button></nav>
<script>
let p = 1;
function render() {
  const rows = []; for (let i = 0; i < 4; i++) rows.push('<li class="job"><a href="/jobs/arr-' + p + '-' + i + '">Arrow Role ' + 'ABCDEFGH'[p * 4 + i - 4] + ' Engineer</a></li>');
  document.getElementById('list').innerHTML = '<ul>' + rows.join('') + '</ul>';
  if (p === 2) document.getElementById('arr').setAttribute('aria-disabled', 'true');
}
document.getElementById('arr').onclick = () => { if (p < 2) { p++; render(); } };
render();
</script></body></html>"""


def _cookie(page):
    pager = "".join(f'<li><a href="/cookie?page={i}">{i}</a></li>' for i in range(1, 3))
    banner = ("""<div id="cookie-banner" style="position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:9999">
      <div style="background:#fff;margin:200px auto;width:400px;padding:20px">We use cookies to improve your
      experience. <button id="ok">Accept all</button></div></div>
      <script>document.getElementById('ok').onclick=()=>{document.cookie='consent=1';
      document.getElementById('cookie-banner').remove();}</script>""")
    return f"""<html><head><title>Careers</title></head><body><h1>Vacancies</h1>
      <ul>{_job_links('ck', page, 3)}</ul><div class="pagination"><ul>{pager}</ul></div>{banner}</body></html>"""


CAROUSEL = """<html><head><title>Careers</title></head><body><h1>Careers - current openings</h1>
<ul>""" + _job_links("car", 1, 3) + """</ul>
<div class="testimonial-carousel"><div id="slide">Great place to work!</div>
<button class="slick-next">›</button></div>
<script>document.querySelector('.slick-next').onclick = () => {
  const ul = document.querySelector('ul'); const li = document.createElement('li');
  li.innerHTML = '<a href="/jobs/car-junk-1">Carousel Junk Role</a>'; ul.appendChild(li); };</script>
</body></html>"""

NOT_LISTING = """<html><head><title>Careers at Paged</title></head><body><h1>Careers</h1>
<p>We are always looking for talent. Write to careers@paged.test.</p>
<a href="/careers-info?page=2" class="next">Next</a></body></html>"""


# ── Patterns seen on real sites in the 14 Oct test run ──────────────────────

# Axis Bank (RippleHire) / ZingHR: jobs arrive as JSON, one page per request,
# rendered as cards with no links; every click also fires an analytics call.
JSON_PAGED = """<html><head><title>Careers</title></head><body><h1>Current job openings</h1>
<div id="list"></div><a id="more" class="view-more">View more</a>
<script>
let p = 0;
function load() {
  p++;
  fetch('/track?e=click').then(r => r.json());
  fetch('/api/jobs?page=' + p).then(r => r.json()).then(d => {
    for (const j of d.jobs) {
      const div = document.createElement('div'); div.className = 'job-card';
      div.textContent = j.title + ' | Job ID: ' + j.jobId + ' | ' + j.location; document.getElementById('list').appendChild(div);
    }
    if (p >= d.pages) document.getElementById('more').remove();
  });
}
document.getElementById('more').onclick = load;
load();
</script></body></html>"""

# Same, but the button never loads jobs — only analytics JSON (must stop fast).
JSON_NOISE = JSON_PAGED.replace("fetch('/api/jobs?page=' + p)", "fetch(p === 1 ? '/api/jobs?page=1' : '/track?e=more')") \
                       .replace("for (const j of d.jobs)", "for (const j of (d.jobs || []))") \
                       .replace("if (p >= d.pages)", "if (d.pages && p >= d.pages && false)")

# AU Small Finance Bank: job links plus an FAQ whose "See more" buttons must
# not be clicked.
FAQ_DECOY = """<html><head><title>Careers</title></head><body><h1>Careers - open positions</h1>
<section class="openings"><ul>""" + "".join(
    f'<li class="job"><a href="/jobs/faq-{i}">{t}</a></li>' for i, t in enumerate(["Branch Manager", "Credit Analyst", "Teller"])) + \
"""</ul></section>
<section class="faq-items"><div class="faq-item"><p>How do I apply?</p><button class="see">See more</button></div>
<div class="faq-item"><p>What is the process?</p><button class="see">See more</button></div></section>
<script>document.querySelectorAll('.see').forEach(b => b.onclick = () => {
  const a = document.createElement('a'); a.href = '/jobs/faq-junk'; a.textContent = 'Junk Role Engineer';
  document.querySelector('.openings ul').appendChild(a); });</script></body></html>"""

# Aditya Birla Fashion: "View More Openings" is a target=_blank link to the
# group careers portal on another domain, which lists the rest of the jobs.
OFFSITE_MORE = """<html><head><title>Careers</title></head><body><h1>Careers - current openings</h1>
<ul>""" + "".join(f'<li class="job"><a href="/jobs/abf-{i}">{t}</a></li>' for i, t in enumerate(["Store Manager", "Visual Merchandiser"])) + \
"""</ul><a class="viewmoreopening" href="http://careers.paged.test/apparel-retail" target="_blank">View More Openings</a>
</body></html>"""
PORTAL = """<html><head><title>Careers - Fashion and Retail</title></head><body><h1>Job openings - Fashion and Retail</h1>
<ul>""" + "".join(f'<li class="job"><a href="/jobs/portal-{i}">{t}</a></li>' for i, t in enumerate(
    ["Assistant Buyer", "Senior Executive Sourcing", "Area Manager", "Design Lead"])) + "</ul></body></html>"


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        b = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        page = int((q.get("page") or ["1"])[0])
        host = (self.headers.get("Host") or "").split(":")[0]
        if host == "careers.paged.test" and u.path == "/apparel-retail":
            body = PORTAL.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/api/jobs":
            return self._json({"pages": 3, "jobs": [
                {"jobId": f"77{page}{i}", "title": f"{TITLES[(page * 3 + i) % len(TITLES)]} J{page}{i}",
                 "location": "Mumbai", "experience": "2 - 4 Years", "department": "Branch Banking"}
                for i in range(3)]})
        if u.path == "/track":
            return self._json({"ok": 1, "events": [{"name": "click", "ts": 1}]})
        routes = {
            "/jsonpaged": lambda: JSON_PAGED,
            "/jsonnoise": lambda: JSON_NOISE,
            "/faq": lambda: FAQ_DECOY,
            "/offsite": lambda: OFFSITE_MORE,
            "/numbered": lambda: _numbered(page),
            "/numonly": lambda: _numbers_only(page),
            "/loadmore": lambda: LOADMORE,
            "/spa": lambda: SPA_NEXT,
            "/arrow": lambda: ARROW,
            "/cookie": lambda: _cookie(page),
            "/carousel": lambda: CAROUSEL,
            "/careers-info": lambda: NOT_LISTING,
        }
        if u.path in routes:
            body = routes[u.path]()
        elif u.path.startswith("/jobs/"):
            body = (f"<html><head><title>Job</title></head><body><h1>{u.path}</h1>"
                    f"<p>{'Responsibilities include many things. ' * 10}</p></body></html>")
        else:
            self.send_response(404)
            self.end_headers()
            return
        b = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture(scope="module")
def paged_port():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


@pytest.fixture
def paged(paged_port, monkeypatch):
    monkeypatch.setattr(BP, "_BASE_ARGS", BP._BASE_ARGS + [f"--host-resolver-rules=MAP paged.test 127.0.0.1:{paged_port}, MAP *.paged.test 127.0.0.1:{paged_port}"])
    # Description fetches are not what we're testing; skip them for speed.
    async def _no_desc(ctx, jobs):
        return None
    monkeypatch.setattr(S, "_fill_descriptions", _no_desc)


def _scrape(path):
    async def go():
        pool = BP.AsyncBrowserPool()
        try:
            b = await pool.get()
            diag = {}
            jobs = await S.scrape_careers_page(f"http://paged.test{path}", "http://paged.test",
                                               browser=b, diag=diag, company_host="paged.test")
            return jobs, diag
        finally:
            await pool.close()
    return asyncio.run(go())


def _urls(jobs):
    return {j["apply_url"].split("paged.test")[-1] for j in jobs}


def test_numbered_pages(paged):
    jobs, diag = _scrape("/numbered")
    assert _urls(jobs) == {f"/jobs/num-p{p}-{i}" for p in (1, 2, 3) for i in range(4)}, diag
    pg = diag["pagination"]
    assert pg["pages_visited"] == 3 and pg["jobs_added"] == 8, pg


def test_page_numbers_only(paged):
    jobs, diag = _scrape("/numonly")
    assert _urls(jobs) == {f"/jobs/no-p{p}-{i}" for p in (1, 2, 3, 4) for i in range(2)}, diag
    assert [c.split(" ")[0].split("(")[0] for c in diag["pagination"]["clicks"]] == [
        "page_number:2", "page_number:3", "page_number:4"], diag["pagination"]


def test_load_more_button(paged):
    jobs, diag = _scrape("/loadmore")
    assert _urls(jobs) == {f"/jobs/lm-{i}" for i in range(13)}, diag
    assert all(c.startswith("load_more") for c in diag["pagination"]["clicks"]), diag["pagination"]


def test_js_next_button_stops_when_disabled(paged):
    jobs, diag = _scrape("/spa")
    assert _urls(jobs) == {f"/jobs/spa-{p}-{i}" for p in range(3) for i in range(3)}, diag
    assert diag["pagination"]["stopped"] == "next_disabled_last_page", diag["pagination"]


def test_icon_only_arrow(paged):
    jobs, diag = _scrape("/arrow")
    assert _urls(jobs) == {f"/jobs/arr-{p}-{i}" for p in (1, 2) for i in range(4)}, diag
    assert diag["pagination"]["stopped"] == "next_disabled_last_page", diag["pagination"]


def test_cookie_banner_is_accepted_then_pages(paged):
    jobs, diag = _scrape("/cookie")
    assert _urls(jobs) == {f"/jobs/ck-p{p}-{i}" for p in (1, 2) for i in range(3)}, diag
    assert diag["pagination"]["cookie_banner"].startswith("accepted"), diag["pagination"]


def test_carousel_arrow_not_clicked(paged):
    jobs, diag = _scrape("/carousel")
    assert _urls(jobs) == {f"/jobs/car-p1-{i}" for i in range(3)}, diag
    assert diag["pagination"]["clicks"] == [] and diag["pagination"]["stopped"] == "no_pager_found"


def test_no_pagination_on_page_without_jobs(paged):
    jobs, diag = _scrape("/careers-info")
    assert jobs == []
    assert diag.get("pagination", {}).get("skipped") == "no_jobs_on_first_page", diag


# ── Real-site patterns (14 Oct run) ─────────────────────────────────────────

def test_json_pages_are_merged(paged):
    # Axis Bank / ZingHR: each "View more" returns another JSON page; all pages count.
    jobs, diag = _scrape("/jsonpaged")
    assert len(jobs) == 9, (len(jobs), diag.get("pagination"))
    assert diag.get("used_json_capture") is True
    assert "json+3" in " ".join(diag["pagination"]["clicks"]), diag["pagination"]


def test_analytics_json_does_not_keep_clicking(paged):
    # A button that only fires non-job JSON must stop after 2 clicks, not 15.
    jobs, diag = _scrape("/jsonnoise")
    assert len(jobs) == 3, (len(jobs), diag.get("pagination"))
    pg = diag["pagination"]
    assert pg["stopped"] == "no_new_jobs_after_2_clicks" and len(pg["clicks"]) == 2, pg


def test_faq_see_more_not_clicked(paged):
    # AU Small Finance Bank: "See more" in an FAQ is not a pager.
    jobs, diag = _scrape("/faq")
    assert _urls(jobs) == {"/jobs/faq-0", "/jobs/faq-1", "/jobs/faq-2"}, diag
    assert diag["pagination"]["clicks"] == [], diag["pagination"]


def test_view_more_link_to_other_careers_site_is_followed(paged):
    # Aditya Birla Fashion: target=_blank "View More Openings" -> group careers portal.
    jobs, diag = _scrape("/offsite")
    urls = {j["apply_url"] for j in jobs}
    assert {"http://paged.test/jobs/abf-0", "http://paged.test/jobs/abf-1"} <= urls, diag
    assert {f"http://careers.paged.test/jobs/portal-{i}" for i in range(4)} <= urls, diag["pagination"]
    assert "opened_link" in diag["pagination"]["clicks"][0], diag["pagination"]
