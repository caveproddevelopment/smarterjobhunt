#!/usr/bin/env python3
"""
Async SJH.com Ingestion Agent — Railway scheduled-run entrypoint (async version).

Same as run_ingestion_db.py but uses async_ingestion_orchestrator.py instead,
which eliminates Playwright greenlet sync-to-async issues by using pure asyncio.
This is the recommended entry point for Railway deployments.

Writes scraped jobs into the `jobs_staging` landing table (see
agent/job_sink.py's StagingJobSink and backend/routes/staging.py),
tagged with one uuid.uuid4() batch_id per run. Jobs previously active
for a company but not seen in this run still get closed out
immediately (is_active=FALSE) — see StagingJobSink's docstring — but
new/updated listings only reach the live `jobs` table (and the backend
API / frontend search) once that batch is cleaned and promoted.

Pass --auto-clean and/or --auto-promote to call the backend's
staging-review endpoints for this batch once ingestion finishes:
  --auto-clean    POST /api/admin/staging/clean   (rule-based auto
                   approve/reject pass — see routes/staging.py)
  --auto-promote  POST /api/admin/staging/promote (implies --auto-clean;
                   only ever touches rows already 'approved', so it's
                   safe to run unattended even with manual review still
                   in the mix — anything left 'pending' just sits there
                   untouched until someone reviews it, or a later
                   --auto-promote call picks it up)
Both require --backend-url/--admin-key (or BACKEND_URL/ADMIN_API_KEY
env vars) — see routes/auth_utils.py's require_admin_key.

Usage (Railway sets DATABASE_URL automatically):
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python run_ingestion_db_async.py
    python run_ingestion_db_async.py --max-workers 10 --limit 50
    python run_ingestion_db_async.py --auto-clean --auto-promote \
        --backend-url https://api.example.com --admin-key <ADMIN_API_KEY>
"""

import argparse
import asyncio
import os
import sys
import time
import uuid

import psycopg2
import requests

from agent.company_source import PostgresCompanySource
from agent.job_sink import StagingJobSink
from agent.async_ingestion_orchestrator import run


def _call_staging_endpoint(backend_url: str, admin_key: str, path: str, batch_id: str) -> dict:
    """POSTs to one of the backend's staging-review endpoints
    (routes/staging.py) for this run's batch. Raises on any non-2xx
    response or network/timeout error — ingestion itself already
    succeeded and committed by the time this runs, so a failure here
    just means the batch sits in jobs_staging waiting for a manual
    /clean or /promote call, not a lost run."""
    resp = requests.post(
        f"{backend_url.rstrip('/')}{path}",
        json={"batch_id": batch_id},
        headers={"X-Admin-Key": admin_key},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


async def main():
    parser = argparse.ArgumentParser(description="SJH.com ingestion agent — DB-backed async run")
    parser.add_argument("--max-workers", type=int, default=10, help="Concurrent companies to process (default 10)")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N companies (for smoke tests)")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--batch-id", default=None,
                         help="Override the generated batch UUID (mainly for testing or re-running against an existing batch)")
    parser.add_argument("--auto-clean", action="store_true",
                         help="Call POST /api/admin/staging/clean on this batch after ingestion finishes")
    parser.add_argument("--auto-promote", action="store_true",
                         help="Call POST /api/admin/staging/promote on this batch after ingestion finishes "
                              "(implies --auto-clean; only touches rows already 'approved')")
    parser.add_argument("--backend-url", default=os.environ.get("BACKEND_URL"),
                         help="Base URL of the backend API (required for --auto-clean/--auto-promote)")
    parser.add_argument("--admin-key", default=os.environ.get("ADMIN_API_KEY"),
                         help="X-Admin-Key value for the backend's staging endpoints (required for --auto-clean/--auto-promote)")
    args = parser.parse_args()

    if not args.database_url:
        sys.exit("DATABASE_URL not set (pass --database-url or export the env var)")

    if args.auto_promote:
        # promote() only ever touches 'approved' rows, so run clean first
        # or anything auto-approvable never gets there.
        args.auto_clean = True
    if (args.auto_clean or args.auto_promote) and not (args.backend_url and args.admin_key):
        sys.exit("--auto-clean/--auto-promote require --backend-url and --admin-key "
                  "(or BACKEND_URL / ADMIN_API_KEY env vars)")

    batch_id = args.batch_id or str(uuid.uuid4())

    conn = psycopg2.connect(args.database_url)
    try:
        source = PostgresCompanySource(conn, limit=args.limit)
        sink = StagingJobSink(conn, batch_id=batch_id)

        def progress(pct, msg):
            print(f"[{int(pct*100):3d}%] {msg}", flush=True)

        start = time.time()
        summary = await run(source, sink, max_workers=args.max_workers, progress_callback=progress)
        total_elapsed = time.time() - start

        print("\n" + "==" * 30)
        print("RUN SUMMARY")
        print("==" * 30)
        print(f"Batch ID:                {batch_id}")
        print(f"Companies processed:     {summary['companies_total']}")
        print(f"  -> ATS API hit:        {summary['companies_ats_hit']}")
        print(f"  -> Career page scrape: {summary['companies_scraped']}")
        print(f"  -> Failed/unknown:     {summary['companies_failed']}")
        print(f"Jobs staged:             {summary['jobs_found']}")
        print(f"Total wall-clock time:   {total_elapsed:.1f}s")
        print(f"Errors:                  {len(summary['errors'])}")
        if summary["errors"]:
            print("\nFirst 10 errors:")
            for e in summary["errors"][:10]:
                print(f"  - {e}")

        if args.auto_clean:
            print(f"\nCalling /api/admin/staging/clean for batch {batch_id} ...", flush=True)
            try:
                clean_result = _call_staging_endpoint(
                    args.backend_url, args.admin_key, "/api/admin/staging/clean", batch_id
                )
                print(f"  approved={clean_result.get('approved')} "
                      f"rejected={clean_result.get('rejected')} "
                      f"pending={clean_result.get('pending')}", flush=True)
            except Exception as e:
                print(f"  clean call failed: {e}", flush=True)

        if args.auto_promote:
            print(f"Calling /api/admin/staging/promote for batch {batch_id} ...", flush=True)
            try:
                promote_result = _call_staging_endpoint(
                    args.backend_url, args.admin_key, "/api/admin/staging/promote", batch_id
                )
                print(f"  promoted={promote_result.get('promoted')}", flush=True)
            except Exception as e:
                print(f"  promote call failed: {e}", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    asyncio.run(main())