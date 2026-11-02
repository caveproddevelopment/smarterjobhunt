"""The three-way Remote dropdown on /api/jobs and /api/jobs/variant-counts,
and bookmarks that save the remote setting, location and distance.

Same setup as test_country_billing.py (real Postgres, throwaway database,
network faked) -- skipped unless SJH_TEST_DATABASE_URL is set.
"""
import pytest

from test_country_billing import BASE_URL, INDIA_IP, _start_trial, db_url, env  # noqa: F401

pytestmark = pytest.mark.skipif(not BASE_URL, reason="SJH_TEST_DATABASE_URL not set")


@pytest.fixture()
def jobs(env):
    db = env["db"]
    db.execute("DELETE FROM user_job_status; DELETE FROM saved_searches; DELETE FROM jobs")
    db.execute(
        "INSERT INTO companies (name, company_type) VALUES ('Acme Remote Test', 'funded') "
        "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
    )
    company_id = db.fetchone()[0]
    rows = [
        ("Data Analyst", "Austin, TX", "On-site role in our Austin office."),
        ("Data Analyst", "Remote (US)", "Work from anywhere."),
        ("Remote Data Analyst", "New York, NY", "Fully distributed team."),
        ("Data Analyst", "Chicago, IL", "Hybrid; remote Fridays."),  # remote only in description
    ]
    for title, location, text in rows:
        db.execute(
            "INSERT INTO jobs (company_id, title, location, raw_text, source_url) VALUES (%s, %s, %s, %s, %s)",
            (company_id, title, location, text * 20, f"https://acme.example/{title}/{location}"),
        )
    return company_id


def _locations(env, headers, query):
    resp = env["client"].get(f"/api/jobs?title=Data+Analyst&{query}", headers=headers)
    assert resp.status_code == 200, resp.get_json()
    return sorted(job["location"] for job in resp.get_json()["jobs"])


def test_remote_modes(env, jobs):
    _, headers, _ = _start_trial(env)
    everything = ["Austin, TX", "Chicago, IL", "New York, NY", "Remote (US)"]
    assert _locations(env, headers, "") == everything
    assert _locations(env, headers, "remote=include") == everything
    # 'only': title, location or description mentions remote.
    assert _locations(env, headers, "remote=only") == ["Chicago, IL", "New York, NY", "Remote (US)"]
    # Old links/bookmarks: remote_only=1 still means 'only'.
    assert _locations(env, headers, "remote_only=1") == ["Chicago, IL", "New York, NY", "Remote (US)"]
    # 'exclude' ("No remote jobs"): title/location only -- the hybrid job
    # that mentions remote in its description stays.
    assert _locations(env, headers, "remote=exclude") == ["Austin, TX", "Chicago, IL"]


def test_location_adds_remote_back_unless_excluded(env, jobs):
    _, headers, _ = _start_trial(env)
    near_austin = "location=Austin%2C+TX&radius_miles=25"
    assert _locations(env, headers, near_austin) == ["Austin, TX", "New York, NY", "Remote (US)"]
    assert _locations(env, headers, near_austin + "&remote=exclude") == ["Austin, TX"]


def test_variant_counts_follow_remote_mode(env, jobs):
    _, headers, _ = _start_trial(env)
    def count(query):
        resp = env["client"].get(f"/api/jobs/variant-counts?variant_title=Data+Analyst&{query}", headers=headers)
        return resp.get_json()["counts"]["Data Analyst"]
    assert count("") == 4
    assert count("remote=only") == 3
    assert count("remote=exclude") == 2


def _save(env, headers, **body):
    payload = {"name": "x", "view_type": "search", "job_title": "Data Analyst", **body}
    return env["client"].post("/api/saved-searches", json=payload, headers=headers)


def test_bookmark_saves_remote_location_and_distance(env, jobs):
    _, headers, _ = _start_trial(env)
    resp = _save(env, headers, name="DA Austin", remote_mode="exclude",
                 location="  Austin, TX ", radius_miles=75)
    assert resp.status_code == 201, resp.get_json()
    saved = resp.get_json()
    assert (saved["remote_mode"], saved["remote_only"], saved["location"], saved["radius_miles"]) == (
        "exclude", False, "Austin, TX", 75)
    listed = env["client"].get("/api/saved-searches", headers=headers).get_json()["saved_searches"]
    assert listed[0]["location"] == "Austin, TX" and listed[0]["remote_mode"] == "exclude"

    # Same search with a different remote setting or place is a different bookmark...
    assert _save(env, headers, name="DA Austin only", remote_mode="only",
                 location="Austin, TX", radius_miles=75).status_code == 201
    assert _save(env, headers, name="DA Austin 25", remote_mode="exclude",
                 location="Austin, TX", radius_miles=25).status_code == 201
    # ...but the exact same one (location in any case) is a duplicate.
    assert _save(env, headers, name="dup", remote_mode="exclude",
                 location="austin, tx", radius_miles=75).status_code == 409


def test_bookmark_defaults_and_legacy_remote_only(env, jobs):
    _, headers, _ = _start_trial(env)
    plain = _save(env, headers, name="plain").get_json()
    assert (plain["remote_mode"], plain["location"], plain["radius_miles"]) == ("include", None, None)
    legacy = _save(env, headers, name="legacy", remote_only=True).get_json()
    assert (legacy["remote_mode"], legacy["remote_only"]) == ("only", True)
    # No location -> no radius, whatever was sent.
    no_place = _save(env, headers, name="np", job_title="Analyst", radius_miles=100).get_json()
    assert no_place["radius_miles"] is None
    # Out-of-range distance is clamped to the slider's range.
    far = _save(env, headers, name="far", job_title="BI", location="Pune", radius_miles=9999).get_json()
    assert far["radius_miles"] == 500


def test_schema_backfills_old_remote_only_bookmarks(env, jobs):
    """Re-applying schema.sql turns old remote_only bookmarks into 'only'."""
    import os
    _, headers, _ = _start_trial(env)
    env["db"].execute(
        "INSERT INTO saved_searches (user_id, name, job_title, remote_only, remote_mode) "
        "SELECT id, 'old', 'Old title', true, 'include' FROM users ORDER BY id DESC LIMIT 1"
    )
    schema = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "db", "schema.sql")
    with open(schema) as f:
        env["db"].execute(f.read())
    env["db"].execute("SELECT remote_mode FROM saved_searches WHERE name = 'old'")
    assert env["db"].fetchone()[0] == "only"
