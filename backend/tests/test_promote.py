"""Database tests for POST /api/admin/staging/promote against a real Postgres.

Skipped unless SJH_TEST_DATABASE_URL points at a disposable database. Each
test builds its own tables in a throwaway schema, so nothing else in that
database is touched. Never point this at production.

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

ADMIN_KEY = "test-admin-key"
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DDL = """
CREATE TABLE companies (id SERIAL PRIMARY KEY, name TEXT NOT NULL UNIQUE);
CREATE TABLE jobs (
    id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL, department TEXT, location TEXT,
    date_posted DATE NOT NULL DEFAULT CURRENT_DATE, source_url TEXT, raw_text TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true, scraped_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE UNIQUE INDEX ON jobs (company_id, source_url) WHERE source_url IS NOT NULL;
CREATE TABLE jobs_staging (
    id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL, department TEXT, location TEXT,
    date_posted DATE NOT NULL DEFAULT CURRENT_DATE, source_url TEXT, raw_text TEXT,
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT now(), batch_id UUID NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'pending', reject_reason TEXT, promoted_at TIMESTAMPTZ);
"""


def _with_schema(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options={quote('-csearch_path=' + schema)}"


@pytest.fixture
def setup(monkeypatch):
    schema = "t_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(BASE_URL)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE SCHEMA {schema}")
    url = _with_schema(BASE_URL, schema)

    conn = psycopg2.connect(url)
    conn.autocommit = True
    conn.cursor().execute(DDL)

    # The app reads DATABASE_URL and ADMIN_API_KEY at import time.
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    monkeypatch.syspath_prepend(BACKEND_DIR)
    for name in [m for m in sys.modules if m in ("app", "config") or m.startswith(("routes", "db"))]:
        del sys.modules[name]
    import app as app_module

    client = app_module.create_app().test_client()
    yield client, conn

    conn.close()
    admin.cursor().execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def _promote(client, batch_id):
    return client.post(
        "/api/admin/staging/promote",
        json={"batch_id": batch_id},
        headers={"X-Admin-Key": ADMIN_KEY},
    )


def test_existing_job_is_never_overwritten(setup):
    client, conn = setup
    cur = conn.cursor()
    batch = str(uuid.uuid4())
    cur.execute("INSERT INTO companies (name) VALUES ('Acme') RETURNING id")
    company_id = cur.fetchone()[0]
    url = "https://jobs.example.com/acme/1"

    cur.execute(
        "INSERT INTO jobs (company_id, title, source_url, raw_text, is_active) "
        "VALUES (%s, 'Old', %s, 'old text', false)",
        (company_id, url),
    )
    cur.execute("SELECT scraped_at FROM jobs WHERE source_url = %s", (url,))
    old_scraped_at = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO jobs_staging (company_id, title, source_url, raw_text, batch_id, review_status) "
        "VALUES (%s, 'New', %s, 'new text', %s, 'approved')",
        (company_id, url, batch),
    )

    resp = _promote(client, batch)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["inserted"] == 0
    assert body["skipped_existing"] == 1
    assert body["promoted"] == 1

    cur.execute("SELECT title, raw_text, is_active, scraped_at FROM jobs WHERE source_url = %s", (url,))
    assert cur.fetchone() == ("Old", "old text", False, old_scraped_at)
    cur.execute("SELECT promoted_at IS NOT NULL FROM jobs_staging WHERE batch_id = %s", (batch,))
    assert cur.fetchone()[0] is True


def test_new_link_is_inserted(setup):
    client, conn = setup
    cur = conn.cursor()
    batch = str(uuid.uuid4())
    cur.execute("INSERT INTO companies (name) VALUES ('Acme') RETURNING id")
    company_id = cur.fetchone()[0]
    url = "https://jobs.example.com/acme/2"

    cur.execute(
        "INSERT INTO jobs_staging (company_id, title, source_url, batch_id, review_status) "
        "VALUES (%s, 'Data Engineer', %s, %s, 'approved')",
        (company_id, url, batch),
    )

    body = _promote(client, batch).get_json()
    assert body["inserted"] == 1
    assert body["skipped_existing"] == 0
    assert body["promoted"] == 1

    cur.execute("SELECT title FROM jobs WHERE source_url = %s", (url,))
    assert cur.fetchone()[0] == "Data Engineer"


def test_repromote_is_a_no_op(setup):
    client, conn = setup
    cur = conn.cursor()
    batch = str(uuid.uuid4())
    cur.execute("INSERT INTO companies (name) VALUES ('Acme') RETURNING id")
    company_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO jobs_staging (company_id, title, source_url, batch_id, review_status) "
        "VALUES (%s, 'SRE', 'https://jobs.example.com/acme/3', %s, 'approved')",
        (company_id, batch),
    )

    _promote(client, batch)
    body = _promote(client, batch).get_json()
    assert body == {"batch_id": batch, "inserted": 0, "skipped_existing": 0, "promoted": 0}
