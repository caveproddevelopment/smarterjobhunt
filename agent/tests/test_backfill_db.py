"""Database tests for run_description_backfill.py and
run_reactivate_returning_jobs.py against a real Postgres.

Skipped unless SJH_TEST_DATABASE_URL points at a disposable database. Each
test builds its own tables in a throwaway schema, so nothing else in that
database is touched. Network fetches are faked.

    SJH_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/sjh_test python -m pytest tests -q
"""
import asyncio
import os
import uuid
from urllib.parse import quote

import pytest

psycopg2 = pytest.importorskip("psycopg2")

import run_description_backfill as BF
import run_reactivate_returning_jobs as RA
from agent.description_fetch import FetchResult

BASE_URL = os.environ.get("SJH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="SJH_TEST_DATABASE_URL not set")

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

DESC = "A real description of the role with responsibilities and requirements. " * 3


def _with_schema(url: str, schema: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}options={quote('-csearch_path=' + schema)}"


@pytest.fixture
def db():
    schema = "t_" + uuid.uuid4().hex[:10]
    admin = psycopg2.connect(BASE_URL)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE SCHEMA {schema}")
    url = _with_schema(BASE_URL, schema)
    conn = psycopg2.connect(url)
    conn.cursor().execute(DDL)
    conn.commit()
    yield url, conn
    conn.close()
    admin.cursor().execute(f"DROP SCHEMA {schema} CASCADE")
    admin.close()


def _q(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() if cur.description else None
    conn.commit()
    return rows


def _seed(conn):
    """Old batch + new batch. In the new batch:
       new-1  new job, no description          -> fetched
       new-2  new job, fetch fails (404)       -> recorded, try 1
       new-3  new job, already 3 failures      -> skipped
       prod-1 already in production            -> skipped (and reactivated if inactive)
       rej-1  rejected row                     -> skipped
       ok-1   already has a description        -> untouched"""
    _q(conn, "INSERT INTO companies (name) VALUES ('Acme'), ('Beta')")
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    rows = [
        (1, "Old", "https://acme.example.com/j/old", None, old, "2026-10-13 02:00+00", "pending"),
        (1, "New 1", "https://acme.example.com/j/new-1", None, new, "2026-10-15 02:00+00", "pending"),
        (1, "New 1 dup", "https://acme.example.com/j/new-1", "", new, "2026-10-15 02:00+00", "pending"),
        (1, "New 2", "https://acme.example.com/j/new-2", None, new, "2026-10-15 02:00+00", "pending"),
        (2, "New 3", "https://beta.example.com/j/new-3", None, new, "2026-10-15 02:00+00", "pending"),
        (2, "Prod 1", "https://beta.example.com/j/prod-1", None, new, "2026-10-15 02:00+00", "pending"),
        (2, "Rej 1", "https://beta.example.com/j/rej-1", None, new, "2026-10-15 02:00+00", "rejected"),
        (2, "OK 1", "https://beta.example.com/j/ok-1", DESC, new, "2026-10-15 02:00+00", "pending"),
    ]
    with conn.cursor() as cur:
        for r in rows:
            cur.execute("""INSERT INTO jobs_staging (company_id, title, source_url, raw_text, batch_id,
                           scraped_at, review_status) VALUES (%s,%s,%s,%s,%s,%s,%s)""", r)
        cur.execute("""INSERT INTO jobs (company_id, title, source_url, raw_text, is_active, scraped_at)
                       VALUES (2, 'Prod 1 (prod title)', 'https://beta.example.com/j/prod-1', %s, FALSE,
                               '2026-10-10 02:00+00')""", (DESC,))
        cur.execute("""INSERT INTO jobs (company_id, title, source_url, raw_text, is_active)
                       VALUES (1, 'Gone', 'https://acme.example.com/j/gone', %s, FALSE)""", (DESC,))
        cur.execute(BF.FAILURES_DDL)
        cur.execute("""INSERT INTO description_fetch_failures (company_id, source_url, tries, last_error)
                       VALUES (2, 'https://beta.example.com/j/new-3', 3, 'http_404')""")
    conn.commit()
    return old, new


def _fake_fetch(calls):
    async def fake(url, renderer):
        calls.append(url)
        if url.endswith("new-2"):
            return FetchResult(False, source="page", error="http_404")
        return FetchResult(True, text=DESC, source="page")
    return fake


def test_dry_run_counts_and_writes_nothing(db, capsys):
    url, conn = db
    _old, new = _seed(conn)
    _q(conn, "DROP TABLE description_fetch_failures")
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        assert asyncio.run(BF.main(["--database-url", url, "--dry-run"])) == 0
    out = capsys.readouterr().out
    assert calls == []
    assert f"batch {new}" in out
    assert "to fetch this run:               3" in out      # new-1, new-2, new-3 (no failures table yet)
    assert "already in production:  1" in out
    assert _q(conn, "SELECT to_regclass('description_fetch_failures')")[0][0] is None


def test_backfill_fills_only_jobs_not_in_production(db, capsys):
    url, conn = db
    _old, new = _seed(conn)
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        assert asyncio.run(BF.main(["--database-url", url])) == 0
    assert sorted(calls) == ["https://acme.example.com/j/new-1", "https://acme.example.com/j/new-2"]
    got = dict(_q(conn, "SELECT title, raw_text FROM jobs_staging"))
    assert got["New 1"] == DESC and got["New 1 dup"] == DESC   # both rows of the same link
    assert got["New 2"] is None
    assert got["Prod 1"] is None and got["Rej 1"] is None and got["Old"] is None
    assert got["OK 1"] == DESC
    fails = dict(_q(conn, "SELECT source_url, tries FROM description_fetch_failures"))
    assert fails == {"https://acme.example.com/j/new-2": 1, "https://beta.example.com/j/new-3": 3}
    assert "Descriptions filled:      1  (2 row(s) updated)" in capsys.readouterr().out


def test_failed_link_dropped_after_three_tries(db):
    url, conn = db
    _seed(conn)
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        for _ in range(4):
            asyncio.run(BF.main(["--database-url", url]))
    assert calls.count("https://acme.example.com/j/new-2") == 3
    assert _q(conn, "SELECT tries FROM description_fetch_failures WHERE source_url LIKE %s",
              ("%new-2",))[0][0] == 3


def test_transient_failure_not_counted(db):
    url, conn = db
    _seed(conn)

    async def fake(u, r):
        return FetchResult(False, source="workday", error="http_429", transient=True)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", fake)
        asyncio.run(BF.main(["--database-url", url]))
    assert _q(conn, "SELECT tries, last_error FROM description_fetch_failures WHERE source_url LIKE %s",
              ("%new-1",))[0] == (0, "http_429")


def test_recovery_mode_on_backup_table(db):
    url, conn = db
    _old, new = _seed(conn)
    _q(conn, """CREATE TABLE deleted_no_raw_text_jobs_staging_backup AS
                SELECT * FROM jobs_staging WHERE raw_text IS NULL OR btrim(raw_text) = ''""")
    _q(conn, "DELETE FROM jobs_staging WHERE raw_text IS NULL OR btrim(raw_text) = ''")
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        assert asyncio.run(BF.main(["--database-url", url, "--table",
                                    "deleted_no_raw_text_jobs_staging_backup", "--all-batches"])) == 0
    assert "https://acme.example.com/j/old" in calls       # all batches
    filled = dict(_q(conn, "SELECT title, raw_text FROM deleted_no_raw_text_jobs_staging_backup"))
    assert filled["Old"] == DESC and filled["New 1"] == DESC and filled["Prod 1"] is None
    assert _q(conn, "SELECT COUNT(*) FROM jobs_staging")[0][0] == 1   # live staging untouched


def test_limit(db):
    url, conn = db
    _seed(conn)
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        asyncio.run(BF.main(["--database-url", url, "--limit", "1"]))
    assert len(calls) == 1


# ── reactivation ─────────────────────────────────────────────────────────────

def test_reactivate_dry_run_then_apply(db, capsys):
    url, conn = db
    _old, new = _seed(conn)
    _q(conn, """INSERT INTO jobs (company_id, title, source_url, raw_text, is_active)
                VALUES (1, 'Back but no desc', 'https://acme.example.com/j/new-2', NULL, FALSE)""")
    assert RA.main(["--database-url", url, "--dry-run"]) == 0
    assert _q(conn, "SELECT is_active FROM jobs WHERE title LIKE 'Prod 1%%'")[0][0] is False
    assert "1 inactive production job(s)" in capsys.readouterr().out

    assert RA.main(["--database-url", url]) == 0
    assert "Reactivated 1 returning jobs" in capsys.readouterr().out
    rows = {t: (a, s, rt) for t, a, s, rt in
            _q(conn, "SELECT title, is_active, scraped_at > '2026-10-10 02:00+00', raw_text FROM jobs")}
    assert rows["Prod 1 (prod title)"] == (True, True, DESC)   # title + description unchanged, scraped_at bumped
    assert rows["Gone"][0] is False               # not in latest scrape
    assert rows["Back but no desc"][0] is False   # no description in production

    assert RA.main(["--database-url", url]) == 0  # idempotent
    assert "Reactivated 0 returning jobs" in capsys.readouterr().out


def test_reactivate_uses_latest_batch_only(db):
    url, conn = db
    old, _new = _seed(conn)
    _q(conn, """INSERT INTO jobs (company_id, title, source_url, raw_text, is_active)
                VALUES (1, 'Seen only in old batch', 'https://acme.example.com/j/old', %s, FALSE)""", (DESC,))
    RA.main(["--database-url", url])
    assert _q(conn, "SELECT is_active FROM jobs WHERE title = 'Seen only in old batch'")[0][0] is False
    RA.main(["--database-url", url, "--batch-id", old])
    assert _q(conn, "SELECT is_active FROM jobs WHERE title = 'Seen only in old batch'")[0][0] is True


def test_dropped_link_retried_after_seven_days(db):
    url, conn = db
    _seed(conn)
    _q(conn, "UPDATE description_fetch_failures SET last_tried_at = now() - interval '8 days'")
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        asyncio.run(BF.main(["--database-url", url]))
    assert "https://beta.example.com/j/new-3" in calls


def test_listing_anchor_links_skipped(db):
    url, conn = db
    _old, new = _seed(conn)
    _q(conn, """INSERT INTO jobs_staging (company_id, title, source_url, batch_id, scraped_at)
                VALUES (1, 'Anchor', 'https://acme.example.com/careers#job-7', %s, '2026-10-15 02:00+00')""", (new,))
    calls = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(BF, "fetch_description", _fake_fetch(calls))
        asyncio.run(BF.main(["--database-url", url]))
    assert not any("#job-" in c for c in calls)


def test_old_failures_table_layout_stops_with_instructions(db):
    url, conn = db
    _seed(conn)
    _q(conn, "DROP TABLE description_fetch_failures")
    _q(conn, """CREATE TABLE description_fetch_failures (source_url TEXT PRIMARY KEY, attempts INTEGER,
                last_error TEXT, last_attempt_at TIMESTAMPTZ)""")
    with pytest.raises(SystemExit) as e:
        asyncio.run(BF.main(["--database-url", url]))
    assert "RENAME TO description_fetch_failures_old" in str(e.value)
