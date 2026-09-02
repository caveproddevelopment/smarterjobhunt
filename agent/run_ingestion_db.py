#!/usr/bin/env python3
"""
SJH.com Ingestion Agent — Railway scheduled-run entrypoint.

Unlike run_ingestion.py (CSV in, CSV out — for local smoke tests), this
reads the company list from the Postgres `companies` table and writes
scraped jobs into the `jobs_staging` landing table (see
agent/job_sink.py's StagingJobSink and backend/routes/staging.py),
tagged with one uuid.uuid4() batch_id per run. jobs_staging is fully
cleared (DELETE FROM jobs_staging) right before this run starts, so
it only ever holds the current scrape's fresh rows -- any rows from a
prior run still 'pending' review are lost when the next run kicks off,
not just already-promoted ones. Jobs previously active
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

Usage (Railway sets DATABASE_URL automatically if you link the Postgres
plugin to this service; set it yourself for local runs):

    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python run_ingestion_db.py
    python run_ingestion_db.py --max-workers 15 --limit 50   # smoke test
    python run_ingestion_db.py --auto-clean --auto-promote \
        --backend-url https://api.example.com --admin-key <ADMIN_API_KEY>

This is the command to put in Railway's "Custom Start Command" for the
agent service, with a Cron Schedule set (e.g. `0 2 * * *` for nightly
at 2am). Companies live in the DB — seed/update them with
seed_companies.py, not by editing this script.

Forced-exit fix (2026-09-02, matching ingestion_orchestrator.py's new
per-company watchdog): if that watchdog abandons a stuck company, its
worker thread isn't forcibly killed — it may keep running in the
background even after run() returns with a complete, correct summary.
Python's concurrent.futures.thread module registers its own atexit hook
that joins *every* ThreadPoolExecutor worker thread it ever created, for
the whole process, the moment the interpreter starts shutting down —
regardless of whether we called shutdown(wait=True) ourselves. Left
alone, that means the script (and the Railway deploy) would still hang
at exit waiting on that one abandoned thread, even though every real
piece of work (staging writes, --auto-clean/--auto-promote calls) is
already done. The __main__ block below calls os._exit() after
everything finishes, which skips that shutdown sequence entirely and
lets the process actually terminate.
"""

import argparse
import os
import sys
import time
import traceback
import uuid

import psycopg2
import requests

from agent.company_source import PostgresCompanySource
from agent.job_sink import StagingJobSink
from agent.ingestion_orchestrator import run


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


def main():
    parser = argparse.ArgumentParser(description="SJH.com ingestion agent — DB-backed run")
    parser.add_argument("--max-workers", type=int, default=10, help="Concurrent companies to process (default 10)")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N companies (for smoke tests)")
    parser.add_argument(
        "--company-type",
        choices=["funded", "fortune500", "indianmajor", "midsize", "healthcare"],
        default=None,
        help="Only process companies tagged with this type (default: all)"
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
        # Clear jobs_staging before this run starts, so the table only ever
        # holds the current scrape's fresh dataset -- no leftover rows from
        # prior batches (pending, approved-unpromoted, rejected, or already
        # promoted all get wiped equally). If you're not running with
        # --auto-clean/--auto-promote every time, anything still sitting
        # 'pending' from the last run is lost here, not just old batches.
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
        print(f"[run_ingestion_db] Cleared {cleared} row(s) from jobs_staging before this run.", flush=True)

        source = PostgresCompanySource(conn, limit=args.limit, company_type=args.company_type)
        sink = StagingJobSink(conn, batch_id=batch_id)

        def progress(pct, msg):
            print(f"[{int(pct*100):3d}%] {msg}", flush=True)

        start = time.time()
        summary = run(source, sink, max_workers=args.max_workers, progress_callback=progress)
        total_elapsed = time.time() - start

        print("\n" + "=" * 60)
        print("RUN SUMMARY")
        print("=" * 60)
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
        _exit_code = main()
    except SystemExit as _e:
        _exit_code = _e.code
    except Exception:
        traceback.print_exc()
        _exit_code = 1

    sys.stdout.flush()
    sys.stderr.flush()

    # Force real process termination — see the module docstring's
    # "Forced-exit fix" note. A normal `sys.exit()` here would still hang
    # if the watchdog in ingestion_orchestrator.py abandoned a stuck
    # company, because Python's own thread-pool cleanup tries to join
    # that thread at interpreter shutdown no matter what we do above it.
    if _exit_code is None:
        _exit_code = 0
    elif not isinstance(_exit_code, int):
        # SystemExit(<string message>) case — the message was already
        # printed by the default handling; just exit non-zero.
        print(_exit_code, file=sys.stderr)
        _exit_code = 1
    os._exit(_exit_code)