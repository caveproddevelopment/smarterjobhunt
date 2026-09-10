#!/usr/bin/env python3
"""
Async SJH.com Ingestion Agent — Railway scheduled-run entrypoint (async version).

Same as run_ingestion_db.py but uses async_ingestion_orchestrator.py instead,
which eliminates Playwright greenlet sync-to-async issues by using pure asyncio.
This is the recommended entry point for Railway deployments.

Writes scraped jobs into the `jobs_staging` landing table (see
agent/job_sink.py's StagingJobSink and backend/routes/staging.py),
tagged with one uuid.uuid4() batch_id per run, in sequential chunks of
--batch-size companies at a time (default 500) — see
async_ingestion_orchestrator.py's module docstring for why.

jobs_staging is NOT cleared before a run by default (changed 2026-09-10
— it used to be, unconditionally). Rows accumulate across runs until
you explicitly wipe it with --clear-staging, or promote what you want
to keep via /api/admin/staging/promote. Jobs previously active for a
company but not seen in this run still get closed out immediately
(is_active=FALSE) — see StagingJobSink's docstring — but new/updated
listings only reach the live `jobs` table (and the backend API /
frontend search) once a batch is cleaned and promoted.

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
    python run_ingestion_db_async.py --batch-size 500
    python run_ingestion_db_async.py --clear-staging   # old default behavior
    python run_ingestion_db_async.py --companies-file retry_timeouts.txt
    python run_ingestion_db_async.py --auto-clean --auto-promote \
        --backend-url https://api.example.com --admin-key <ADMIN_API_KEY>

Forced-exit fix (2026-09-10, matching run_ingestion_db.py's existing
fix for the sync pipeline): asyncio.to_thread() calls in
async_ingestion_orchestrator.py (added the same day, see that module's
docstring) mean a hung detect_ats()/fetch_jobs() call now only strands
its own background thread instead of freezing the whole event loop --
but that thread isn't forcibly killed either. Left alone, Python's
concurrent.futures.thread module registers an atexit hook that joins
*every* thread pool worker thread ever created (including asyncio's
default to_thread executor) at normal interpreter shutdown, so the
process would still hang at exit waiting on that one leaked thread even
though every batch had already been written successfully. The
__main__ block below calls os._exit() after asyncio.run(main())
finishes, which skips that shutdown sequence entirely.
"""

import argparse
import asyncio
import os
import sys
import time
import traceback
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
    parser.add_argument("--max-workers", type=int, default=10, help="Concurrent companies to process per batch (default 10)")
    parser.add_argument("--batch-size", type=int, default=500,
                         help="Companies processed and written to jobs_staging per sequential chunk "
                              "(default 500). The shared browser is recycled between chunks. Set this "
                              ">= the total company count to reproduce the old one-shot-at-the-end "
                              "behavior.")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N companies (for smoke tests)")
    parser.add_argument(
        "--company-type",
        choices=["funded", "fortune500", "indianmajor", "midsize", "healthcare"],
        default=None,
        help="Only process companies tagged with this type (default: all)"
    )
    parser.add_argument(
        "--companies-file",
        default=None,
        help="Path to a plain text file, one exact company name per line (must match the "
             "`name` column in Postgres). Scopes this run to only those companies -- e.g. "
             "retrying just the ones that hard-timed-out on a previous run. Combines with "
             "--company-type via AND if both are given. Names with no matching row are "
             "silently skipped."
    )
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
    parser.add_argument("--clear-staging", action="store_true",
                         help="DELETE FROM jobs_staging before this run, wiping every row -- pending, "
                              "approved-unpromoted, rejected, and already-promoted alike -- regardless "
                              "of batch. Off by default as of 2026-09-10: jobs_staging now accumulates "
                              "across runs until you promote what you want to keep (see "
                              "backend/routes/staging.py's /promote). Pass this only when you "
                              "deliberately want a clean slate.")
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

    company_names = None
    if args.companies_file:
        with open(args.companies_file, encoding="utf-8-sig") as f:
            company_names = [line.strip() for line in f if line.strip()]
        print(f"[run_ingestion_db_async] Loaded {len(company_names)} company name(s) from "
              f"{args.companies_file} to scope this run.", flush=True)

    conn = psycopg2.connect(args.database_url)
    try:
        if args.clear_staging:
            cur = conn.cursor()
            try:
                cur.execute("DELETE FROM jobs_staging")
                cleared = cur.rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
            print(f"[run_ingestion_db_async] --clear-staging passed: cleared {cleared} row(s) "
                  f"from jobs_staging before this run.", flush=True)
        else:
            print("[run_ingestion_db_async] jobs_staging left untouched (pass --clear-staging "
                  "to wipe it first).", flush=True)

        source = PostgresCompanySource(conn, limit=args.limit, company_type=args.company_type, names=company_names)
        sink = StagingJobSink(conn, batch_id=batch_id)

        def progress(pct, msg):
            print(f"[{int(pct*100):3d}%] {msg}", flush=True)

        start = time.time()
        summary = await run(
            source, sink,
            max_workers=args.max_workers,
            batch_size=args.batch_size,
            progress_callback=progress,
        )
        total_elapsed = time.time() - start

        print("\n" + "==" * 30)
        print("RUN SUMMARY")
        print("==" * 30)
        print(f"Batch ID:                {batch_id}")
        print(f"Companies processed:     {summary['companies_total']}")
        print(f"  -> ATS API hit:        {summary['companies_ats_hit']}")
        print(f"  -> Career page scrape: {summary['companies_scraped']}")
        print(f"  -> Failed/unknown:     {summary['companies_failed']}")
        print(f"  -> Timed out/abandoned:{summary['companies_timed_out']}")
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
    try:
        _exit_code = asyncio.run(main())
    except SystemExit as _e:
        _exit_code = _e.code
    except Exception:
        traceback.print_exc()
        _exit_code = 1

    sys.stdout.flush()
    sys.stderr.flush()

    # Force real process termination — see the module docstring's
    # "Forced-exit fix" note. A normal script exit here would still hang
    # if a detect_ats()/fetch_jobs() call got stuck on this run, because
    # Python's own thread-pool cleanup tries to join that leaked thread
    # at interpreter shutdown no matter what.
    if _exit_code is None:
        _exit_code = 0
    elif not isinstance(_exit_code, int):
        print(_exit_code, file=sys.stderr)
        _exit_code = 1
    os._exit(_exit_code)