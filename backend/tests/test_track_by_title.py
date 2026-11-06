"""Track Applications scoped to a searched title: Applied / Rejected / Neither
with title=developer only returns developer jobs; with no title, every marked job.
Same throwaway-database setup as test_country_billing.py (needs SJH_TEST_DATABASE_URL)."""
import uuid

from tests.test_country_billing import US_IP, _register, db_url, env  # noqa: F401  (fixtures)


def _seed(env):
    db = env["db"]
    db.execute("INSERT INTO companies (name) VALUES (%s) RETURNING id", (f"Acme {uuid.uuid4().hex[:6]}",))
    cid = db.fetchone()[0]
    ids = {}
    for t in ("Senior Software Developer", "Backend Developer", "Frontend Developer",
              "Product Designer", "UX Designer"):
        db.execute(
            "INSERT INTO jobs (company_id, title, source_url, date_posted) VALUES (%s, %s, %s, CURRENT_DATE) RETURNING id",
            (cid, t, f"https://acme.test/{uuid.uuid4().hex}"))
        ids[t] = db.fetchone()[0]
    return ids


def _titles(env, headers, **q):
    resp = env["client"].get("/api/jobs", query_string=q, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    return sorted(j["title"] for j in resp.get_json()["jobs"])


def test_status_views_follow_the_searched_title(env):
    ids = _seed(env)
    _, h = _register(env["client"], US_IP)
    mark = lambda title, status: env["client"].put(f"/api/job-status/{ids[title]}", json={"status": status}, headers=h)
    assert mark("Senior Software Developer", "applied").status_code == 200
    assert mark("Product Designer", "applied").status_code == 200
    assert mark("Backend Developer", "rejected").status_code == 200

    # With a title: only jobs under that title.
    assert _titles(env, h, status="applied", title="developer") == ["Senior Software Developer"]
    assert _titles(env, h, status="rejected", title="developer") == ["Backend Developer"]
    assert "Frontend Developer" in _titles(env, h, status="neither", title="developer")
    assert not {"Senior Software Developer", "Backend Developer"} & set(_titles(env, h, status="neither", title="developer"))
    assert _titles(env, h, status="applied", title="designer") == ["Product Designer"]

    # No title: every job marked that way, across all searches.
    assert _titles(env, h, status="applied") == ["Product Designer", "Senior Software Developer"]


def _ids(env, headers, **q):
    resp = env["client"].get("/api/jobs", query_string=q, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    return {j["id"] for j in resp.get_json()["jobs"]}


def test_marked_jobs_stay_in_the_normal_list(env):
    ids = _seed(env)
    user_id, h = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    mark = lambda title, status: env["client"].put(f"/api/job-status/{ids[title]}", json={"status": status}, headers=h)
    backend, senior, frontend = ids["Backend Developer"], ids["Senior Software Developer"], ids["Frontend Developer"]
    assert mark("Backend Developer", "rejected").status_code == 200
    assert mark("Senior Software Developer", "applied").status_code == 200
    # the normal ("All") list keeps marked jobs
    normal = _ids(env, h, title="developer")
    assert {backend, senior, frontend} <= normal
    # Neither leaves them out
    neither = _ids(env, h, status="neither", title="developer")
    assert frontend in neither and backend not in neither and senior not in neither
    # and they show under their own Track Applications views
    assert backend in _ids(env, h, status="rejected", title="developer")
    assert senior in _ids(env, h, status="applied", title="developer")
    # clearing the mark brings it back to Neither
    assert env["client"].delete(f"/api/job-status/{backend}", headers=h).status_code in (200, 204)
    assert backend in _ids(env, h, status="neither", title="developer")


def test_variant_counts_include_marked_jobs(env):
    _seed(env)
    user_id, h = _register(env["client"], US_IP)
    count = lambda: env["client"].get("/api/jobs/variant-counts", query_string={"variant_title": "UX Designer"},
                                      headers=h).get_json()["counts"]["UX Designer"]
    before = count()
    env["db"].execute("SELECT id FROM jobs WHERE title = 'UX Designer' ORDER BY id DESC LIMIT 1")
    job_id = env["db"].fetchone()[0]
    env["client"].put(f"/api/job-status/{job_id}", json={"status": "rejected"}, headers=h)
    assert count() == before


def test_sort_newest_and_best_match(env):
    db = env["db"]
    db.execute("INSERT INTO companies (name) VALUES (%s) RETURNING id", (f"Sortco {uuid.uuid4().hex[:6]}",))
    cid = db.fetchone()[0]
    tag = uuid.uuid4().hex[:8]
    phrase = f"Zebra{tag} Wrangler"
    # older job with the title in title + description (perfect match); newer job that only mentions it in the description
    db.execute("INSERT INTO jobs (company_id, title, raw_text, source_url, date_posted) "
               "VALUES (%s, %s, %s, %s, CURRENT_DATE - 5) RETURNING id",
               (cid, phrase, f"We are hiring a {phrase}.", f"https://sort.test/{uuid.uuid4().hex}"))
    titled = db.fetchone()[0]
    db.execute("INSERT INTO jobs (company_id, title, raw_text, source_url, date_posted) "
               "VALUES (%s, 'Office Assistant', %s, %s, CURRENT_DATE) RETURNING id",
               (cid, f"You will support the {phrase} team.", f"https://sort.test/{uuid.uuid4().hex}"))
    described = db.fetchone()[0]
    user_id, h = _register(env["client"], US_IP)
    db.execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    get = lambda **q: [j["id"] for j in env["client"].get(
        "/api/jobs", query_string={"title": phrase, **q}, headers=h).get_json()["jobs"]]
    assert get() == [described, titled]            # default: newest first
    assert get(sort="newest") == [described, titled]
    assert get(sort="match") == [titled, described]


def test_neither_bookmark_keeps_sidebar_filters(env):
    _, h = _register(env["client"], US_IP)
    post = lambda body: env["client"].post("/api/saved-searches", json=body, headers=h)
    resp = post({"name": "Neither Jobs · developer · Austin", "view_type": "status", "status_filter": "neither",
                 "job_title": "developer", "posted_within_days": "7", "company_types": ["funded"],
                 "remote_mode": "only", "location": "Austin, TX", "radius_miles": 25})
    assert resp.status_code == 201, resp.get_json()
    saved = resp.get_json()
    assert saved["company_types"] == ["funded"] and saved["remote_mode"] == "only"
    assert saved["location"] == "Austin, TX" and saved["radius_miles"] == 25
    # same title, different filters -> a second, separate bookmark
    assert post({"name": "Neither Jobs · developer", "view_type": "status", "status_filter": "neither",
                 "job_title": "developer"}).status_code == 201
    # Applied / Rejected bookmarks ignore the sidebar filters
    applied = post({"name": "Applied Jobs · developer", "view_type": "status", "status_filter": "applied",
                    "job_title": "developer", "company_types": ["funded"], "location": "Austin, TX",
                    "remote_mode": "only"}).get_json()
    assert applied["company_types"] == [] and applied["location"] is None and applied["remote_mode"] == "include"
