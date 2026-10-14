"""Unit tests for the 2026-10-13 scraper fixes (no network, no browser).

Run:  python -m pytest tests -q
Cases come from the 7 Oct findings file and Railway logs.
"""
import json
from unittest import mock

import pytest

from agent import platforms as P
from agent import ats_api, ats_detector
from agent.job_json import harvest_jobs_from_json
from agent.async_career_scraper import (
    filter_job_anchors, choose_title, _pick_careers_link, _slug_title,
)
from agent.async_ingestion_orchestrator import _classify_outcome


# ── ATS URL parsing ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("https://job-boards.eu.greenhouse.io/groww", ("greenhouse_eu", "groww")),
    ("https://boards.greenhouse.io/embed/job_board?for=acme&b=x", ("greenhouse", "acme")),
    ("https://jobs.lever.co/dreamsports", ("lever", "dreamsports")),
    ("https://jobs.eu.lever.co/foo", ("lever_eu", "foo")),
    ("https://jobs.ashbyhq.com/bolna", ("ashby", "bolna")),
    ("https://jobs.ashbyhq.com/Local%20Kitchens/abc", ("ashby", "Local%20Kitchens")),
    ("https://apply.workable.com/bharatx/", ("workable", "bharatx")),
    ("https://careers.smartrecruiters.com/Freshworks", ("smartrecruiters", "Freshworks")),
    ("https://fractal.wd1.myworkdayjobs.com/Careers", ("workday", "fractal.wd1.myworkdayjobs.com|fractal|Careers")),
    ("https://uniphore.wd503.myworkdayjobs.com/en-US/Uniphore/job/x", ("workday", "uniphore.wd503.myworkdayjobs.com|uniphore|Uniphore")),
    ("https://gpi-iacriz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1", ("oracle", "gpi-iacriz.fa.ocs.oraclecloud.com|CX_1")),
    ("https://iabiiz.fa.ocs.oraclecloud.com", ("oracle", "iabiiz.fa.ocs.oraclecloud.com|")),
    ("https://acme.recruitee.com/o/engineer", ("recruitee", "acme")),
    ("https://agrostar.darwinbox.in/ms/candidate/careers", None),
])
def test_parse_ats_url(text, expected):
    assert P.parse_ats_url(text) == expected


def test_parse_ats_url_from_html_entity_json():
    # The garbage URLs in the 7 Oct logs came from entity-encoded JSON blobs.
    html = ('{&#34;opensInNewTab&#34;:false,&#34;link&#34;:&#34;https://jll.wd1.myworkdayjobs.com/jllcareers&#34;}'
            ' and "x":"https:\\/\\/gilead.wd1.myworkdayjobs.com\\/gileadcareers"')
    assert P.parse_ats_url(html) == ("workday", "jll.wd1.myworkdayjobs.com|jll|jllcareers")


def test_unescape_literal_newline_does_not_glue_host():
    t = P.unescape_for_scan('"\\nmyworkdayjobs.com"')
    assert "nmyworkdayjobs" not in t


def test_platform_for_url():
    assert P.platform_for_url("https://abfrlcareers.peoplestrong.com/home") == "peoplestrong"
    assert P.platform_for_url("https://zingnext.zinghr.com/portal/embed/careers") == "zinghr"
    assert P.platform_for_url("https://www.acme.com/careers") is None


# ── Page validation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("req,final,title,h1,text,company,expected", [
    ("https://aegisindia.com/careers", "https://aegisindia.com/wp-content/uploads/2021/05/Careers.jpg", "", "", "", "aegisindia.com", "not_html"),
    ("https://www.anandrathiwealth.in/careers", "https://www.anandrathiwealth.in/careers", "Page Not Found", "", "careers", "anandrathiwealth.in", "not_found_page"),
    ("https://www.arya.ag/careers", "https://www.arya.ag/404", "Arya", "", "", "arya.ag", "error_page"),
    ("https://www.crisil.com/careers", "https://www.crisil.com/en/errors/404-error.html", "", "", "", "crisil.com", "error_page"),
    ("https://www.canfinhomes.com/careers", "https://www.canfinhomes.com/Errors/PageNotFound", "", "", "", "canfinhomes.com", "error_page"),
    ("https://www.finolex.com/careers", "https://www.finolex.com/Account/Login", "Login", "", "", "finolex.com", "login_page"),
    ("https://www.bewelldigital.com/careers", "https://www.chicagomovingcompany.org/", "Movers", "", "jobs", "bewelldigital.com", "off_site_redirect"),
    ("https://castled.io/careers", "https://castled.io/lander", "", "", "", "castled.io", "parked_domain"),
    ("https://www.aartiindustries.com/careers", "https://www.hugedomains.com/domain_profile.cfm", "", "", "", "aartiindustries.com", "parked_domain"),
    ("https://www.unitedbreweries.com/careers", "https://www.unitedbreweries.com/age-gate/17109", "UB", "", "careers", "unitedbreweries.com", "age_gate"),
    ("https://www.eatclub.in/careers", "https://eatclub.in/", "EatClub", "", "careers", "eatclub.in", "redirected_home"),
    ("https://www.ntpc.co.in/careers", "https://validate.perfdrive.com/x", "", "", "", "ntpc.co.in", "bot_wall"),
    ("https://www.craftsman.com/contact-us.html", "https://www.craftsman.com/contact-us.html", "Contact Us", "Contact", "Call us at", "craftsman.com", "no_career_content"),
    # legitimate: careers on a hiring platform, on a brand domain, or a sister site
    ("https://www.abfrl.com/careers/", "https://abfrlcareers.peoplestrong.com/home", "Careers", "", "", "abfrl.com", None),
    ("https://www.canarabank.com/careers", "https://canarabank.bank.in/pages/career", "Career", "", "recruitment", "canarabank.com", None),
    ("https://careers.unilever.com/india", "https://careers.unilever.com/india", "Jobs in India", "", "jobs", "hul.co.in", None),
    ("https://acme.com/careers", "https://acme.com/careers", "Careers at Acme", "Join us", "Open roles", "acme.com", None),
])
def test_classify_page(req, final, title, h1, text, company, expected):
    assert P.classify_page(req, final, 200, "text/html", title, h1, text, company_host=company) == expected


def test_registrable_domain():
    assert P.registrable_domain("www.kotak.bank.in") == "kotak.bank.in"
    assert P.registrable_domain("www.3m.co.in") == "3m.co.in"
    assert P.registrable_domain("sjvn.nic.in") == "sjvn.nic.in"
    assert P.registrable_domain("careers.acme.com") == "acme.com"


# ── Ashby / Workday / Workable adapters (requests mocked) ────────────────────

class _Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status
        self.text = json.dumps(data)
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            e = requests.HTTPError(f"{self.status_code}")
            e.response = self
            raise e


def test_ashby_reads_public_api_shape():
    data = {"apiVersion": "1", "jobs": [{
        "id": "131e", "title": "AI Solutions Engineer", "department": "Business", "team": "Business",
        "location": "Bengaluru", "publishedAt": "2026-07-03T14:07:26.107+00:00", "isListed": True,
        "isRemote": False, "jobUrl": "https://jobs.ashbyhq.com/bolna/131e",
        "descriptionPlain": "x" * 300}]}
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(data)) as g:
        jobs = ats_api.fetch_jobs("ashby", "bolna")
    assert g.call_args[0][0] == "https://api.ashbyhq.com/posting-api/job-board/bolna"
    assert jobs == [{
        "title": "AI Solutions Engineer", "department": "Business", "location": "Bengaluru",
        "apply_url": "https://jobs.ashbyhq.com/bolna/131e", "posted_at": "2026-07-03",
        "description_snippet": "x" * 300}]


def test_ashby_probe_matches_jobs_key():
    with mock.patch.object(ats_detector.requests, "get", return_value=_Resp({"jobs": [], "apiVersion": "1"})):
        assert ats_detector._probe_one_api("ashby", "bolna") == ("ashby", "bolna")


def test_ashby_board_name_is_url_quoted():
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp({"jobs": []})) as g:
        ats_api.fetch_jobs("ashby", "Local%20Kitchens")
    assert g.call_args[0][0].endswith("/job-board/Local%20Kitchens")


def test_workday_paginates_and_builds_urls():
    page1 = {"total": 21, "jobPostings": [{"title": f"Job {i}", "externalPath": f"/job/Bangalore/Job-{i}_R{i}",
                                            "locationsText": "Bangalore"} for i in range(20)]}
    page2 = {"total": 0, "jobPostings": [{"title": "Job 20", "externalPath": "/job/Pune/Job-20_R20",
                                          "locationsText": "Pune"}]}
    with mock.patch.object(ats_api.requests, "post", side_effect=[_Resp(page1), _Resp(page2)]) as p:
        jobs = ats_api.fetch_jobs("workday", "fractal.wd1.myworkdayjobs.com|fractal|Careers", fetch_descriptions=False)
    assert p.call_args_list[0][0][0] == "https://fractal.wd1.myworkdayjobs.com/wday/cxs/fractal/Careers/jobs"
    assert len(jobs) == 21
    assert jobs[0]["apply_url"] == "https://fractal.wd1.myworkdayjobs.com/Careers/job/Bangalore/Job-0_R0"


def test_workable_falls_back_to_widget():
    import requests
    def post(*a, **k):
        return _Resp({}, status=404)
    widget = {"name": "X", "jobs": [{"title": "Engineer", "shortcode": "AB12", "url": "https://apply.workable.com/x/j/AB12/",
                                     "city": "Bengaluru", "country": "India", "department": "Tech"}]}
    with mock.patch.object(ats_api.requests, "post", side_effect=post), \
         mock.patch.object(ats_api.requests, "get", return_value=_Resp(widget)):
        jobs = ats_api.fetch_jobs("workable", "x", fetch_descriptions=False)
    assert jobs[0]["title"] == "Engineer" and jobs[0]["location"] == "Bengaluru, India"


def test_oracle_list_shape():
    data = {"items": [{"TotalJobsCount": 2, "requisitionList": [
        {"Id": "101", "Title": "Plant Manager", "PrimaryLocation": "Pune, India", "PostedDate": "2026-09-30",
         "ShortDescriptionStr": "y" * 150},
        {"Id": "102", "Title": "Sales Lead", "PrimaryLocation": "Delhi, India", "PostedDate": "2026-09-29",
         "ShortDescriptionStr": "z" * 150}]}]}
    with mock.patch.object(ats_api.requests, "get", return_value=_Resp(data)):
        jobs = ats_api.fetch_jobs("oracle", "iabiiz.fa.ocs.oraclecloud.com|CX_1")
    assert [j["apply_url"] for j in jobs] == [
        "https://iabiiz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/101",
        "https://iabiiz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/102"]


# ── JSON harvesting ──────────────────────────────────────────────────────────

def test_harvest_darwinbox_like_json():
    data = {"status": 1, "message": {"jobs": [
        {"id": "a1b2c3", "title": "Area Sales Manager", "location": "Indore", "department": "Sales", "experience": "3-5 yrs"},
        {"id": "d4e5f6", "title": "Agronomist", "location": "Pune", "department": "Agri", "experience": "1-3 yrs"},
    ]}}
    jobs = harvest_jobs_from_json([("https://agrostar.darwinbox.in/ms/candidateapi/job?page=1", data)],
                                  "https://agrostar.darwinbox.in/ms/candidate/careers", on_platform=True)
    assert [j["title"] for j in jobs] == ["Area Sales Manager", "Agronomist"]
    assert jobs[0]["apply_url"].endswith("#job-a1b2c3")
    assert jobs[0]["location"] == "Indore"


def test_harvest_ignores_location_facets_and_blog_posts():
    facets = {"facets": [{"name": "Bengaluru", "city": "Bengaluru", "count": 4},
                         {"name": "Pune", "city": "Pune", "count": 2}]}
    blog = {"posts": [{"title": "Our culture at Acme", "author": "x", "slug": "culture"},
                      {"title": "Q3 results", "author": "y", "slug": "q3"}]}
    assert harvest_jobs_from_json([("https://acme.com/api/search", facets), ("https://acme.com/api/blog", blog)],
                                  "https://acme.com/careers") == []


# ── Link filter ──────────────────────────────────────────────────────────────

def test_apply_now_links_titled_from_card():
    anchors = [
        {"href": "https://www.olectra.com/openings/senior-design-engineer", "text": "Apply Now", "card": "Senior Design Engineer", "aria": "", "sel": -1},
        {"href": "https://www.olectra.com/openings/quality-inspector", "text": "Apply Now", "card": "Quality Inspector", "aria": "", "sel": -1},
        {"href": "https://www.olectra.com/about", "text": "About", "card": "", "aria": "", "sel": -1},
    ]
    jobs = filter_job_anchors(anchors, "https://www.olectra.com/career")
    assert [j["title"] for j in jobs] == ["Senior Design Engineer", "Quality Inspector"]


def test_generic_text_without_detail_url_rejected():
    anchors = [{"href": "https://acme.com/careers", "text": "Apply Now", "card": "Join our team", "aria": "", "sel": -1},
               {"href": "https://acme.com/careers/life", "text": "Life at Acme", "card": "", "aria": "", "sel": 2}]
    assert filter_job_anchors(anchors, "https://acme.com/jobs") == []


def test_whole_card_link_text_reduced_to_heading():
    t, rescued = choose_title("Senior Software Engineer\nBengaluru · Full time · 3-6 years\nPosted 2 days ago",
                              "Senior Software Engineer", "", "https://www.testmuai.com/career/jobdetails/123")
    assert t == "Senior Software Engineer"


def test_slug_title():
    assert _slug_title("https://careers.shiprocket.in/jobs/senior-data-engineer-12345") == "Senior Data Engineer"
    assert _slug_title("https://x.com/jobs/12345") == ""


def test_best_selector_group_wins():
    nav = [{"href": "https://a.com/jobs", "text": "Jobs", "card": "", "aria": "", "sel": 0}]
    real = [{"href": f"https://a.com/careers/role-{i}", "text": f"Backend Engineer {i}", "card": "", "aria": "", "sel": 2}
            for i in range(5)]
    jobs = filter_job_anchors(nav + real, "https://a.com/careers")
    assert len(jobs) == 5


# ── Careers link discovery ───────────────────────────────────────────────────

def test_pick_careers_link_hindi_and_people_culture():
    anchors = [{"href": "https://www.nhpcindia.com/welcome/job", "text": "कैरियर"},
               {"href": "https://www.nhpcindia.com/about", "text": "About"}]
    assert _pick_careers_link(anchors, "https://www.nhpcindia.com/") == "https://www.nhpcindia.com/welcome/job"
    anchors = [{"href": "https://www.adityabirlarealestate.com/career", "text": "People & Culture"}]
    assert _pick_careers_link(anchors, "https://www.adityabirlarealestate.com/").endswith("/career")


def test_pick_careers_link_skips_images_and_prefers_platform():
    anchors = [{"href": "https://www.mankindpharma.com/wp-content/uploads/2024/11/careers.webp", "text": "Careers"},
               {"href": "https://tvsmsampark.darwinbox.in/ms/candidate/careers", "text": "Explore openings"}]
    assert "darwinbox" in _pick_careers_link(anchors, "https://www.mankindpharma.com/")


# ── Sitemap ──────────────────────────────────────────────────────────────────

def test_pick_careers_from_sitemap():
    urls = ["https://www.sbicard.com/en/personal/credit-cards.page",
            "https://www.sbicard.com/en/who-we-are/careers.page",
            "https://www.sbicard.com/en/who-we-are/careers/job-123.page"]
    assert ats_detector.pick_careers_from_sitemap(urls, "www.sbicard.com") == \
        "https://www.sbicard.com/en/who-we-are/careers.page"


# ── Outcome classification ───────────────────────────────────────────────────

def test_classify_invalid_page_and_bot_wall():
    d = {"scrape": {"outcome": "invalid_page", "page_invalid": "login_page", "final_url": "https://x/login"}, "ats": {}}
    assert _classify_outcome("career_scrape", 0, None, d)[0] == "scrape_invalid_page"
    d = {"scrape": {"outcome": "invalid_page", "page_invalid": "bot_wall"}, "ats": {}}
    assert _classify_outcome("career_scrape", 0, None, d)[0] == "blocked_bot_wall"
    d = {"detect": {"homepage_status": "error: SSLError"}, "discover": {"outcome": "homepage_load_failed: Error: net::ERR_SSL_VERSION_OR_CIPHER_MISMATCH"}, "ats": {}}
    assert _classify_outcome("unknown", 0, None, d)[0] == "website_ssl_error"


def test_vendor_marketing_site_is_not_a_job_board():
    from agent.platforms import platform_for_url
    assert platform_for_url("https://www.darwinbox.com/?utm_source=x") is None
    assert platform_for_url("https://keka.com/") is None
    assert platform_for_url("https://bharatpe.darwinbox.in/ms/candidate/careers") == "darwinbox"
    assert platform_for_url("https://acciojob.keka.com/careers") == "keka"
    assert platform_for_url("https://wellfound.com/company/acme/jobs") == "wellfound"
    assert platform_for_url("https://job-boards.greenhouse.io/able") == "greenhouse"
