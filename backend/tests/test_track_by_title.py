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


def test_marked_jobs_only_show_in_their_track_view(env):
    ids = _seed(env)
    user_id, h = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    mark = lambda title, status: env["client"].put(f"/api/job-status/{ids[title]}", json={"status": status}, headers=h)
    backend, senior, frontend = ids["Backend Developer"], ids["Senior Software Developer"], ids["Frontend Developer"]
    assert backend in _ids(env, h, title="developer")
    assert mark("Backend Developer", "rejected").status_code == 200
    assert mark("Senior Software Developer", "applied").status_code == 200
    # gone from the normal search...
    normal = _ids(env, h, title="developer")
    assert frontend in normal and backend not in normal and senior not in normal
    # ...but listed under the Track Applications views
    assert backend in _ids(env, h, status="rejected", title="developer")
    assert senior in _ids(env, h, status="applied", title="developer")
    # clearing the mark brings it back
    assert env["client"].delete(f"/api/job-status/{backend}", headers=h).status_code in (200, 204)
    assert backend in _ids(env, h, title="developer")
    # someone else's marks don't hide jobs for this user
    other_id, other = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (other_id,))
    assert senior in _ids(env, other, title="developer")


def test_variant_counts_skip_marked_jobs(env):
    _seed(env)
    user_id, h = _register(env["client"], US_IP)
    count = lambda: env["client"].get("/api/jobs/variant-counts", query_string={"variant_title": "UX Designer"},
                                      headers=h).get_json()["counts"]["UX Designer"]
    before = count()
    env["db"].execute("SELECT id FROM jobs WHERE title = 'UX Designer' ORDER BY id DESC LIMIT 1")
    job_id = env["db"].fetchone()[0]
    env["client"].put(f"/api/job-status/{job_id}", json={"status": "rejected"}, headers=h)
    assert count() == before - 1
