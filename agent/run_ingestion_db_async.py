#!/usr/bin/env python3

"""
Async SJH.com Ingestion Agent — Railway scheduled-run entrypoint (async version).

Same as run_ingestion_db.py but uses async_ingestion_orchestrator.py instead,
which eliminates Playwright greenlet sync-to-async issues by using pure asyncio.

Usage (Railway sets DATABASE_URL automatically):
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python run_ingestion_db_async.py
    python run_ingestion_db_async.py --max-workers 10 --limit 50

This is the recommended entry point for Railway deployments.
"""

import argparse
import asyncio
import os
import sys
import time

import psycopg2

from agent.company_source import PostgresCompanySource
from agent.job_sink import PostgresJobSink
from agent.async_ingestion_orchestrator import run


async def main():
    parser = argparse.ArgumentParser(description="SJH.com ingestion agent — DB-backed async run")
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
        summary = await run(source, sink, max_workers=args.max_workers, progress_callback=progress)
        total_elapsed = time.time() - start

        print("\n" + "==" * 30)
        print("RUN SUMMARY")
        print("==" * 30)
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
    asyncio.run(main())

