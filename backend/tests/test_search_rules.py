"""Database tests for GET /api/jobs search rules: a job title is required
(except for the scoped no-title views), and results come 20 at a time.

Skipped unless SJH_TEST_DATABASE_URL points at a disposable database.

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
JOB_COUNT = 45


@pytest.fixture
def setup(monkeypatch):
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
    for i in range(JOB_COUNT):
        cur.execute(
            "INSERT INTO jobs (company_id, title, date_posted) VALUES (%s, %s, CURRENT_DATE - %s)",
            (company_id, f"Data Analyst {i}", i),
        )

    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.syspath_prepend(BACKEND_DIR)
    for name in [m for m in sys.modules if m in ("app", "config") or m.startswith(("routes", "db"))]:
        del sys.modules[name]
    import app as app_module

    yield app_module.create_app().test_client(), company_id

    conn.close()
    admin.cursor().execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def test_no_title_search_is_refused(setup):
    client, _ = setup
    resp = client.get("/api/jobs")
    assert resp.status_code == 400
    assert "title" in resp.get_json()["error"].lower()
    assert client.get("/api/jobs", query_string={"posted_days": 7, "remote_only": 1}).status_code == 400


def test_scoped_no_title_views_still_work(setup):
    client, company_id = setup
    assert client.get("/api/jobs", query_string={"company_type": "funded"}).status_code == 200
    assert client.get("/api/jobs", query_string={"company_id": company_id}).status_code == 200
    # Track Applications: logged out it's simply empty, but not refused.
    assert client.get("/api/jobs", query_string={"status": "applied"}).status_code == 200


def test_title_search_works_without_subscription(setup):
    client, _ = setup
    body = client.get("/api/jobs", query_string={"title": "Data Analyst"}).get_json()
    assert body["total_count"] == JOB_COUNT
    # Free callers still only get titles (the rest is blurred on the page).
    assert set(body["jobs"][0]) == {"id", "title"}


def test_pages_are_capped_at_20(setup):
    client, _ = setup
    first = client.get("/api/jobs", query_string={"title": "Data Analyst", "limit": 500}).get_json()
    assert first["count"] == 20
    assert first["total_count"] == JOB_COUNT

    last = client.get("/api/jobs", query_string={"title": "Data Analyst", "offset": 40}).get_json()
    assert last["count"] == JOB_COUNT - 40

    ids = set()
    for offset in (0, 20, 40):
        page = client.get("/api/jobs", query_string={"title": "Data Analyst", "offset": offset}).get_json()
        ids.update(j["id"] for j in page["jobs"])
    assert len(ids) == JOB_COUNT


def test_company_jobs_endpoint_is_capped_too(setup):
    client, company_id = setup
    resp = client.get(f"/api/companies/{company_id}/jobs", query_string={"limit": 500})
    assert len(resp.get_json()["jobs"]) == 20
