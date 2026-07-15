#!/usr/bin/env python3
"""
SJH.com Ingestion Agent — Railway scheduled-run entrypoint.

Unlike run_ingestion.py (CSV in, CSV out — for local smoke tests), this
reads the company list from the Postgres `companies` table and writes
scraped jobs straight back into `jobs`, so the backend API (and the
frontend search) sees new listings right after this finishes.

Usage (Railway sets DATABASE_URL automatically if you link the Postgres
plugin to this service; set it yourself for local runs):

    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python run_ingestion_db.py
    python run_ingestion_db.py --max-workers 15 --limit 50   # smoke test

This is the command to put in Railway's "Custom Start Command" for the
agent service, with a Cron Schedule set (e.g. `0 2 * * *` for nightly
at 2am). Companies live in the DB — seed/update them with
seed_companies.py, not by editing this script.
"""

import argparse
import os
import sys
import time

import psycopg2

from agent.company_source import PostgresCompanySource
from agent.job_sink import PostgresJobSink
from agent.ingestion_orchestrator import run


def main():
    parser = argparse.ArgumentParser(description="SJH.com ingestion agent — DB-backed run")
    parser.add_argument("--max-workers", type=int, default=10, help="Concurrent companies to process (default 10)")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N companies (for smoke tests)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.database_url:
        sys.exit("DATABASE_URL not set (pass --database-url or export the env var)")

    conn = psycopg2.connect(args.database_url)
    try:
        source = PostgresCompanySource(conn, limit=args.limit)
        sink = PostgresJobSink(conn)

        def progress(pct, msg):
            print(f"[{int(pct*100):3d}%] {msg}", flush=True)

        start = time.time()
        summary = run(source, sink, max_workers=args.max_workers, progress_callback=progress)
        total_elapsed = time.time() - start

        print("\n" + "=" * 60)
        print("RUN SUMMARY")
        print("=" * 60)
        print(f"Companies processed:     {summary['companies_total']}")
        print(f"  -> ATS API hit:        {summary['companies_ats_hit']}")
        print(f"  -> Career page scrape: {summary['companies_scraped']}")
        print(f"  -> Failed/unknown:     {summary['companies_failed']}")
        print(f"Jobs found:              {summary['jobs_found']}")
        print(f"Total wall-clock time:   {total_elapsed:.1f}s")
        print(f"Errors:                  {len(summary['errors'])}")
        if summary["errors"]:
            print("\nFirst 10 errors:")
            for e in summary["errors"][:10]:
                print(f"  - {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
