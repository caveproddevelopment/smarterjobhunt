#!/usr/bin/env python3
"""
Reactivate returning jobs (added 2026-10-15).

A production job is set to inactive when a scrape doesn't see it (see
StagingJobSink's closeout). If a later scrape sees it again, nothing turned
it back on: promote doesn't touch jobs that are already in production. This
step does, and only that:

    UPDATE jobs SET is_active = TRUE, scraped_at = <time it was seen>
    for inactive jobs whose company_id + source_url appear in the latest
    scrape batch in jobs_staging, and that already have a description
    (raw_text of at least 100 characters) in production.

Title, description, date posted and everything else stay as they are, so
existing production rows are never overwritten.

Nightly order:
    1. run_ingestion_db_async.py         (scrape)
    2. run_description_backfill.py       (descriptions)
    3. run_reactivate_returning_jobs.py  (this script)
    4. cleanup (delete staged rows with no description) and promote
It must run before the cleanup: a returning job's staged row often has no
description (the backfill skips jobs already in production), so the cleanup
would delete the only evidence that the job came back.

Usage:
    python run_reactivate_returning_jobs.py --dry-run     # preview count + sample, no changes
    python run_reactivate_returning_jobs.py               # latest batch
    python run_reactivate_returning_jobs.py --batch-id <uuid>
"""

import argparse
import os
import sys

import psycopg2

MIN_DESCRIPTION_CHARS = 100

# Candidates: inactive production jobs seen in the batch (any review status:
# a row being in the scrape means the posting is live, same rule the closeout
# uses), that have a real description in production.
_CANDIDATES_CTE = """
WITH seen AS (
    SELECT company_id, source_url, MAX(scraped_at) AS seen_at
    FROM jobs_staging
    WHERE batch_id::text = %(batch)s AND source_url IS NOT NULL AND btrim(source_url) <> ''
    GROUP BY company_id, source_url
), candidates AS (
    SELECT j.id, s.seen_at
    FROM jobs j
    JOIN seen s ON s.company_id = j.company_id AND s.source_url = j.source_url
    WHERE j.is_active = FALSE
      AND j.raw_text IS NOT NULL AND char_length(btrim(j.raw_text)) >= %(min_chars)s
)
"""

PREVIEW_SQL = _CANDIDATES_CTE + "SELECT COUNT(*) FROM candidates"

SAMPLE_SQL = _CANDIDATES_CTE + """
SELECT c.name, j.title, j.source_url, j.scraped_at AS last_seen_before
FROM candidates x JOIN jobs j ON j.id = x.id JOIN companies c ON c.id = j.company_id
ORDER BY c.name, j.title LIMIT 10
"""

APPLY_SQL = _CANDIDATES_CTE + """
UPDATE jobs j
SET is_active = TRUE, scraped_at = COALESCE(x.seen_at, now())
FROM candidates x
WHERE j.id = x.id
"""


def latest_batch(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT batch_id::text FROM jobs_staging GROUP BY batch_id ORDER BY MAX(scraped_at) DESC LIMIT 1")
        row = cur.fetchone()
        return row[0] if row else None


def reactivate(conn, batch_id: str, dry_run: bool = False) -> dict:
    """Preview, then (unless dry_run) apply in one transaction. Returns
    {"batch_id", "candidates", "reactivated", "sample"}."""
    params = {"batch": batch_id, "min_chars": MIN_DESCRIPTION_CHARS}
    try:
        with conn.cursor() as cur:
            cur.execute(PREVIEW_SQL, params)
            n = cur.fetchone()[0]
            cur.execute(SAMPLE_SQL, params)
            sample = cur.fetchall()
            reactivated = 0
            if not dry_run and n:
                cur.execute(APPLY_SQL, params)
                reactivated = cur.rowcount
        if dry_run:
            conn.rollback()
        else:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"batch_id": batch_id, "candidates": n, "reactivated": reactivated, "sample": sample}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Set returning jobs back to active")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--batch-id", default=None, help="Scrape batch to check (default: latest in jobs_staging)")
    p.add_argument("--dry-run", action="store_true", help="Preview only; change nothing")
    args = p.parse_args(argv)
    if not args.database_url:
        sys.exit("DATABASE_URL not set (pass --database-url or export the env var)")

    conn = psycopg2.connect(args.database_url)
    try:
        batch_id = args.batch_id or latest_batch(conn)
        if not batch_id:
            print("jobs_staging is empty; nothing to do.")
            return 0
        res = reactivate(conn, batch_id, dry_run=args.dry_run)
        print(f"Batch {batch_id}: {res['candidates']} inactive production job(s) reappeared in this scrape "
              f"and have a description.")
        for name, title, url, last in res["sample"]:
            print(f"  - {name}: {title}  ({url}, last seen {last})")
        if args.dry_run:
            print("Dry run: nothing changed.")
        else:
            print(f"Reactivated {res['reactivated']} returning jobs")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
