#!/usr/bin/env python3
"""
Description backfill (added 2026-10-15).

The nightly scrape (run_ingestion_db_async.py) no longer opens every job's
page for its description. This script runs right after it and fetches
descriptions ONLY for scraped jobs that are not already in production
(no row in `jobs` with the same company_id + source_url), so we stop
re-downloading descriptions we already have.

Nightly order:
    1. python run_ingestion_db_async.py            (scrape -> jobs_staging)
    2. python run_description_backfill.py          (this script)
    3. python run_reactivate_returning_jobs.py     (returning jobs back to active)
    4. cleanup (delete staged rows with no description) and promote, as today
Step 2 must run before the cleanup in step 4, or the jobs it would have
filled are deleted before it gets to them.

Where descriptions come from, per job (see agent/description_fetch.py):
    platform API (Workday, SmartRecruiters, Oracle, Workable, Greenhouse,
    Lever) -> the job page over plain HTTP -> the job page rendered in
    headless Chromium when it is a JavaScript page.

Politeness and limits:
    --per-host 2       at most 2 requests at a time to any one site, 0.5s apart
    --limit 20000      unique job links per run
    --max-minutes 120  stop starting new fetches after this long
Failures: each failed link is recorded in description_fetch_failures and
skipped for 7 days (--retry-after-days) once it has failed 3 times
(--max-tries). Rate limits (429), server errors and timeouts are recorded but
don't count as a try.

Rows are only ever filled in where raw_text is empty or shorter than 100
characters; nothing else about a row is changed.

Usage:
    python run_description_backfill.py --dry-run          # counts only, no fetching, no writes
    python run_description_backfill.py --limit 2000       # first real run
    python run_description_backfill.py                    # latest batch in jobs_staging
    python run_description_backfill.py --batch-id <uuid>
    python run_description_backfill.py --all-batches

Recovery mode for the rows backed up on 14 Oct (no re-scrape needed):
    python run_description_backfill.py --table deleted_no_raw_text_jobs_staging_backup --all-batches --dry-run
    python run_description_backfill.py --table deleted_no_raw_text_jobs_staging_backup --all-batches
"""

import argparse
import asyncio
import os
import sys
import time
import traceback
from collections import Counter, defaultdict, deque
from urllib.parse import urlsplit

import psycopg2
from psycopg2 import sql

from agent import ats_api
from agent.description_fetch import MIN_DESCRIPTION_CHARS, FetchResult, Renderer, fetch_description

PER_HOST_DELAY_SECONDS = 0.5
JOB_TIMEOUT_SECONDS = 90

FAILURES_DDL = """
CREATE TABLE IF NOT EXISTS description_fetch_failures (
    company_id      INTEGER NOT NULL,
    source_url      TEXT NOT NULL,
    tries           INTEGER NOT NULL DEFAULT 0,
    last_error      TEXT,
    last_source     TEXT,
    first_failed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_tried_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, source_url)
);
"""

# Shared API hosts: all companies on these platforms hit the same server,
# so they share one per-host limit.
_SHARED_API_HOST = {
    "smartrecruiters": "api.smartrecruiters.com",
    "greenhouse":      "boards-api.greenhouse.io",
    "lever":           "api.lever.co",
}


def host_key(url: str) -> str:
    source = ats_api.detail_source_for_url(url)
    if source in _SHARED_API_HOST:
        return _SHARED_API_HOST[source]
    try:
        return urlsplit(url).hostname or "?"
    except Exception:
        return "?"


def interleave_by_host(links: list[tuple]) -> list[tuple]:
    """Round-robin across hosts so the workers aren't all queued behind one
    site's 2-request limit (selection order groups links by company)."""
    by_host: dict[str, deque] = defaultdict(deque)
    for link in links:
        by_host[host_key(link[1])].append(link)
    queues = sorted(by_host.values(), key=len, reverse=True)
    out = []
    while queues:
        nxt = []
        for q in queues:
            out.append(q.popleft())
            if q:
                nxt.append(q)
        queues = nxt
    return out


# ─────────────────────────────────────────────────────────────────────────────
# DB
# ─────────────────────────────────────────────────────────────────────────────

def table_columns(conn, table: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema = current_schema() AND table_name = %s""", (table,))
        return {r[0] for r in cur.fetchall()}


def table_exists(conn, table: str) -> bool:
    return bool(table_columns(conn, table))


def latest_batch(conn, table: str, cols: set[str]):
    order = "scraped_at" if "scraped_at" in cols else "batch_id"
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT batch_id FROM {t} GROUP BY batch_id ORDER BY MAX({o}) DESC LIMIT 1")
                    .format(t=sql.Identifier(table), o=sql.Identifier(order)))
        row = cur.fetchone()
        return row[0] if row else None


def build_filters(cols: set[str], batch_id) -> tuple[sql.Composed, list]:
    """WHERE clause for rows that still need a description."""
    parts = [sql.SQL("t.source_url IS NOT NULL AND btrim(t.source_url) <> ''"),
             # "#job-N" links point at a listing page, not a job page of its own
             sql.SQL("t.source_url NOT LIKE '%%#job-%%'"),
             sql.SQL("(t.raw_text IS NULL OR char_length(btrim(t.raw_text)) < %s)")]
    params: list = [MIN_DESCRIPTION_CHARS]
    if batch_id is not None:
        parts.append(sql.SQL("t.batch_id::text = %s"))
        params.append(str(batch_id))
    if "review_status" in cols:
        parts.append(sql.SQL("t.review_status <> 'rejected'"))
    if "promoted_at" in cols:
        parts.append(sql.SQL("t.promoted_at IS NULL"))
    return sql.SQL(" AND ").join(parts), params


def select_links(conn, table: str, cols: set[str], batch_id, max_tries: int,
                 failures_table_exists: bool, retry_dropped: bool, retry_after_days: float = 7) -> dict:
    """Unique (company_id, source_url) links that need a description, plus
    counts of what was excluded and why."""
    where, params = build_filters(cols, batch_id)
    t = sql.Identifier(table)
    with conn.cursor() as cur:
        cur.execute(sql.SQL("""
            SELECT t.company_id, t.source_url, COUNT(*) AS n_rows,
                   EXISTS (SELECT 1 FROM jobs j
                           WHERE j.company_id = t.company_id AND j.source_url = t.source_url) AS in_prod
            FROM {t} t WHERE {where}
            GROUP BY t.company_id, t.source_url
            ORDER BY t.company_id, t.source_url
        """).format(t=t, where=where), params)
        rows = cur.fetchall()

        tries = {}
        if failures_table_exists:
            # A link that hit max_tries is dropped for retry_after_days, then
            # gets another chance (a page can come back after an outage).
            cur.execute("""SELECT company_id, source_url, tries,
                                  last_tried_at > now() - make_interval(secs => %s) AS recent
                           FROM description_fetch_failures""", (retry_after_days * 86400,))
            tries = {(c, u): (n if recent else 0) for c, u, n, recent in cur.fetchall()}

    todo, in_prod, dropped = [], 0, 0
    rows_needing = 0
    for company_id, url, n_rows, is_prod in rows:
        rows_needing += n_rows
        if is_prod:
            in_prod += 1
            continue
        if not retry_dropped and tries.get((company_id, url), 0) >= max_tries:
            dropped += 1
            continue
        todo.append((company_id, url, n_rows))
    return {"todo": todo, "links_total": len(rows), "rows_needing": rows_needing,
            "in_prod": in_prod, "dropped": dropped}


class Writer:
    """Applies results from the event loop thread; commits every N writes."""

    def __init__(self, conn, table: str, batch_id, commit_every: int = 100):
        self.conn = conn
        self.batch_id = batch_id
        self.commit_every = commit_every
        self.pending = 0
        self.rows_updated = 0
        t = sql.Identifier(table)
        batch_clause = sql.SQL(" AND batch_id::text = %s") if batch_id is not None else sql.SQL("")
        self.update_sql = sql.SQL("""
            UPDATE {t} SET raw_text = %s
            WHERE company_id = %s AND source_url = %s
              AND (raw_text IS NULL OR char_length(btrim(raw_text)) < %s){b}
        """).format(t=t, b=batch_clause)

    def _batch_params(self):
        return [str(self.batch_id)] if self.batch_id is not None else []

    def success(self, company_id, url, text):
        with self.conn.cursor() as cur:
            cur.execute(self.update_sql, [text, company_id, url, MIN_DESCRIPTION_CHARS, *self._batch_params()])
            self.rows_updated += cur.rowcount
            cur.execute("DELETE FROM description_fetch_failures WHERE company_id = %s AND source_url = %s",
                        (company_id, url))
        self._tick()

    def failure(self, company_id, url, error, source, counts: bool):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO description_fetch_failures (company_id, source_url, tries, last_error, last_source)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (company_id, source_url) DO UPDATE
                SET tries = description_fetch_failures.tries + EXCLUDED.tries,
                    last_error = EXCLUDED.last_error, last_source = EXCLUDED.last_source,
                    last_tried_at = now()
            """, (company_id, url, 1 if counts else 0, error[:300], source))
        self._tick()

    def _tick(self):
        self.pending += 1
        if self.pending >= self.commit_every:
            self.flush()

    def flush(self):
        self.conn.commit()
        self.pending = 0


# ─────────────────────────────────────────────────────────────────────────────
# Fetch loop
# ─────────────────────────────────────────────────────────────────────────────

async def run_fetches(todo, writer: Writer, *, concurrency: int, per_host: int,
                      max_seconds: float, render: bool, render_pages: int,
                      progress_every: int = 500) -> dict:
    stats = Counter()
    by_source_ok = Counter()
    by_source_fail = Counter()
    errors = Counter()
    host_sems: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(per_host))
    deadline = time.monotonic() + max_seconds
    renderer = Renderer(max_pages=render_pages) if render else None
    queue: asyncio.Queue = asyncio.Queue()
    for item in todo:
        queue.put_nowait(item)
    started = time.monotonic()
    # API and plain-page fetches run in threads (requests is blocking); give
    # the loop enough of them for --concurrency.
    from concurrent.futures import ThreadPoolExecutor
    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=concurrency + 4))

    async def worker():
        while True:
            try:
                company_id, url, _n = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if time.monotonic() >= deadline:
                stats["not_started_time_limit"] += 1
                continue
            async with host_sems[host_key(url)]:
                try:
                    res = await asyncio.wait_for(fetch_description(url, renderer), timeout=JOB_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    res = FetchResult(False, source="?", error=f"timeout >{JOB_TIMEOUT_SECONDS}s", transient=True)
                except Exception as e:   # fetch_description shouldn't raise; be safe
                    res = FetchResult(False, source="?", error=f"crash {type(e).__name__}: {e}"[:200])
                await asyncio.sleep(PER_HOST_DELAY_SECONDS)   # small gap between requests to one site
            try:
                if res.ok:
                    writer.success(company_id, url, res.text)
                    stats["filled"] += 1
                    by_source_ok[res.source] += 1
                else:
                    writer.failure(company_id, url, res.error, res.source, counts=not res.transient)
                    stats["failed_transient" if res.transient else "failed"] += 1
                    by_source_fail[res.source] += 1
                    errors[res.error.split(":")[0][:40]] += 1
            except Exception as e:
                writer.conn.rollback()
                writer.pending = 0
                stats["db_error"] += 1
                print(f"[backfill] DB write failed for {url}: {e}", flush=True)
            done = stats["filled"] + stats["failed"] + stats["failed_transient"]
            if done and done % progress_every == 0:
                rate = done / max(1.0, time.monotonic() - started)
                print(f"[backfill] {done}/{len(todo)} done  filled={stats['filled']} "
                      f"failed={stats['failed']} transient={stats['failed_transient']}  "
                      f"{rate:.1f}/s", flush=True)

    try:
        await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))
    finally:
        writer.flush()
        if renderer is not None:
            await renderer.close()
    return {"stats": stats, "ok": by_source_ok, "fail": by_source_fail, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Fetch descriptions for scraped jobs not already in production")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--table", default="jobs_staging",
                   help="Table to fill (default jobs_staging). Use deleted_no_raw_text_jobs_staging_backup "
                        "for the 14 Oct recovery.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--batch-id", default=None, help="Only this batch (default: the latest batch in --table)")
    g.add_argument("--all-batches", action="store_true", help="Every batch in --table")
    p.add_argument("--limit", type=int, default=20000, help="Max unique job links to fetch this run (default 20000)")
    p.add_argument("--max-minutes", type=float, default=120, help="Stop starting new fetches after this (default 120)")
    p.add_argument("--per-host", type=int, default=2, help="Max concurrent requests per site (default 2)")
    p.add_argument("--concurrency", type=int, default=16, help="Total concurrent fetches (default 16)")
    p.add_argument("--render-pages", type=int, default=4, help="Max concurrent headless-browser pages (default 4)")
    p.add_argument("--no-render", action="store_true", help="Never use the headless browser")
    p.add_argument("--max-tries", type=int, default=3, help="Skip links that failed this many times (default 3)")
    p.add_argument("--retry-dropped", action="store_true", help="Also retry links that hit --max-tries")
    p.add_argument("--retry-after-days", type=float, default=7,
                   help="A dropped link gets another try after this many days (default 7)")
    p.add_argument("--dry-run", action="store_true", help="Show counts per source; fetch and write nothing")
    return p.parse_args(argv)


async def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.database_url:
        sys.exit("DATABASE_URL not set (pass --database-url or export the env var)")

    conn = psycopg2.connect(args.database_url)
    try:
        cols = table_columns(conn, args.table)
        if not cols:
            sys.exit(f"Table {args.table!r} not found")
        missing = {"company_id", "source_url", "raw_text"} - cols
        if missing:
            sys.exit(f"Table {args.table!r} is missing column(s): {', '.join(sorted(missing))}")

        batch_id = None
        if args.batch_id:
            batch_id = args.batch_id
        elif not args.all_batches:
            if "batch_id" not in cols:
                sys.exit(f"{args.table} has no batch_id column; pass --all-batches")
            batch_id = latest_batch(conn, args.table, cols)
            if batch_id is None:
                print(f"[backfill] {args.table} is empty; nothing to do.")
                return 0

        failures_exists = table_exists(conn, "description_fetch_failures")
        if failures_exists:
            fcols = table_columns(conn, "description_fetch_failures")
            if not {"company_id", "tries", "last_tried_at"} <= fcols:
                sys.exit("description_fetch_failures exists with an older layout (probably from the "
                         "jobbeggar_agent_2026-10-15.zip build). Rename it, then re-run:\n"
                         "  ALTER TABLE description_fetch_failures RENAME TO description_fetch_failures_old;")
        if not args.dry_run and not failures_exists:
            with conn.cursor() as cur:
                cur.execute(FAILURES_DDL)
            conn.commit()
            failures_exists = True

        sel = select_links(conn, args.table, cols, batch_id, args.max_tries, failures_exists, args.retry_dropped,
                           args.retry_after_days)
        conn.commit()
        todo = sel["todo"]
        over_limit = max(0, len(todo) - args.limit)
        todo = interleave_by_host(todo)[: args.limit]

        scope = f"batch {batch_id}" if batch_id is not None else "all batches"
        print("=" * 60)
        print(f"DESCRIPTION BACKFILL — {args.table}, {scope}{'  (DRY RUN)' if args.dry_run else ''}")
        print("=" * 60)
        print(f"Rows without a description:        {sel['rows_needing']}")
        print(f"Unique job links among them:       {sel['links_total']}")
        print(f"  skipped, already in production:  {sel['in_prod']}")
        print(f"  skipped, failed {args.max_tries}+ times (retry after {args.retry_after_days:g} days):".ljust(36) + f" {sel['dropped']}")
        print(f"  to fetch this run:               {len(todo)}"
              + (f"  ({over_limit} left for later runs, --limit {args.limit})" if over_limit else ""))
        src = Counter(ats_api.detail_source_for_url(u) or "page" for _, u, _ in todo)
        print("Planned fetches by source:")
        for s, n in src.most_common():
            print(f"  {n:7d}  {s}")
        hosts = Counter(host_key(u) for _, u, _ in todo)
        print(f"Sites: {len(hosts)}. Largest:")
        for h, n in hosts.most_common(10):
            print(f"  {n:7d}  {h}")
        sys.stdout.flush()

        if args.dry_run or not todo:
            return 0

        writer = Writer(conn, args.table, batch_id)
        t0 = time.time()
        out = await run_fetches(todo, writer, concurrency=args.concurrency, per_host=args.per_host,
                                max_seconds=args.max_minutes * 60, render=not args.no_render,
                                render_pages=args.render_pages)
        st = out["stats"]
        print("\nRESULT")
        print(f"Descriptions filled:      {st['filled']}  ({writer.rows_updated} row(s) updated)")
        print(f"Failed (counts a try):    {st['failed']}")
        print(f"Failed (429/5xx/timeout): {st['failed_transient']}  (not counted; retried next run)")
        if st["not_started_time_limit"]:
            print(f"Not started (time limit): {st['not_started_time_limit']}")
        if st["db_error"]:
            print(f"DB write errors:          {st['db_error']}")
        print(f"Elapsed:                  {time.time() - t0:.0f}s")
        print("Filled by source:  " + ", ".join(f"{k}={v}" for k, v in out["ok"].most_common()))
        print("Failed by source:  " + ", ".join(f"{k}={v}" for k, v in out["fail"].most_common()))
        print("Top failure reasons: " + ", ".join(f"{k}={v}" for k, v in out["errors"].most_common(8)))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except SystemExit as e:
        code = e.code
    except Exception:
        traceback.print_exc()
        code = 1
    sys.stdout.flush()
    sys.stderr.flush()
    if code is None:
        code = 0
    elif not isinstance(code, int):
        print(code, file=sys.stderr)
        code = 1
    # Same forced exit as run_ingestion_db_async.py: a hung requests call in a
    # to_thread worker must not keep the process alive after the work is done.
    os._exit(code)
