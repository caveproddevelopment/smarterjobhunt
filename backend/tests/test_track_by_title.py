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
