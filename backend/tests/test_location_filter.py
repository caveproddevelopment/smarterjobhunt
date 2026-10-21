"""Database tests for the Location + distance filter on GET /api/jobs and
GET /api/jobs/variant-counts.

Skipped unless SJH_TEST_DATABASE_URL points at a disposable database. Each
test loads db/schema.sql into a throwaway schema. Never point this at
production.

    cd backend
    SJH_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/sjh_test python -m pytest tests -q
"""
import os
import sys
import uuid
from urllib.parse import quote

import pytest

psycopg2 = pytest.importorskip("psycopg2")

BASE_URL = os.environ.get("SJH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="SJH_TEST_DATABASE_URL not set")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

JOBS = [
    ("Data Analyst", "Austin, TX"),
    ("Data Analyst", "Round Rock, Texas"),
    ("Data Analyst", "San Antonio, TX"),
    ("Data Analyst", "Shreveport, LA"),
    ("Data Analyst", "Denver, CO"),
    ("Data Analyst", "Bengaluru, Karnataka, India"),
    ("Data Analyst", "Remote - US"),
    ("Remote Data Analyst", None),
    ("Data Analyst", "Multiple Locations"),
]


@pytest.fixture
def client(monkeypatch):
    schema = "t_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(BASE_URL)
    admin.autocommit = True
    admin.cursor().execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    admin.cursor().execute("CREATE EXTENSION IF NOT EXISTS citext")
    admin.cursor().execute(f"CREATE SCHEMA {schema}")
    sep = "&" if "?" in BASE_URL else "?"
    url = f"{BASE_URL}{sep}options={quote(f'-csearch_path={schema},public')}"

    conn = psycopg2.connect(url)
    conn.autocommit = True
    cur = conn.cursor()
    with open(os.path.join(BACKEND_DIR, "db", "schema.sql"), encoding="utf-8") as f:
        cur.execute(f.read())
    cur.execute("INSERT INTO companies (name) VALUES ('Acme') RETURNING id")
    company_id = cur.fetchone()[0]
    for title, location in JOBS:
        cur.execute(
            "INSERT INTO jobs (company_id, title, location) VALUES (%s, %s, %s)",
            (company_id, title, location),
        )

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.syspath_prepend(BACKEND_DIR)
    for name in [m for m in sys.modules if m in ("app", "config") or m.startswith(("routes", "db"))]:
        del sys.modules[name]
    import app as app_module
    import routes.jobs as jobs_module

    # Return full rows (locations included) as if the caller subscribed.
    monkeypatch.setattr(jobs_module, "_has_premium_access", lambda user_id: True)

    yield app_module.create_app().test_client()

    conn.close()
    admin.cursor().execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def _locations(client, **params):
    # No title here, so browse one Company Database (a no-title search
    # is otherwise refused -- see test_search_rules.py).
    params.setdefault("company_type", "funded")
    resp = client.get("/api/jobs", query_string=params)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    return sorted(str(j["location"]) for j in body["jobs"]), body


def test_no_location_returns_everything(client):
    locations, body = _locations(client)
    assert len(locations) == len(JOBS)
    assert "location_resolved" not in body


def test_city_radius_includes_remote(client):
    locations, body = _locations(client, location="Austin, TX", radius_miles=50)
    assert locations == sorted(["Austin, TX", "Round Rock, Texas", "Remote - US", "None"])
    assert body["location_resolved"] == "Austin, TX, US"
    assert body["total_count"] == 4

    wider, _ = _locations(client, location="Austin, TX", radius_miles=100)
    assert "San Antonio, TX" in wider


def test_state_with_radius(client):
    locations, _ = _locations(client, location="Texas", radius_miles=50)
    assert "Shreveport, LA" in locations
    assert "Denver, CO" not in locations


def test_unknown_place_is_reported_not_applied(client):
    locations, body = _locations(client, location="Narnia", radius_miles=50)
    assert body["location_not_found"] is True
    assert len(locations) == len(JOBS)


def test_variant_counts_respect_location(client):
    resp = client.get("/api/jobs/variant-counts", query_string={
        "variant_title": "Data Analyst", "location": "India", "radius_miles": 50,
    })
    assert resp.status_code == 200
    # Bengaluru + the two remote jobs
    assert resp.get_json()["counts"] == {"Data Analyst": 3}
