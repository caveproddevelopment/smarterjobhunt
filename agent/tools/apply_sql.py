"""Apply one or more .sql files to $DATABASE_URL, in order.

Used to run db/migrations/*.sql and db/fixes/*.sql from inside the Railway
container (the image has no psql). Every file it's meant for is safe to re-run.

    python tools/apply_sql.py db/migrations/2026-10-13_listing_status.sql \
                              db/fixes/2026-10-13_india_findings.sql
"""
import os
import sys

import psycopg2


def main(paths: list[str]) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("[apply_sql] DATABASE_URL not set")
    if not paths:
        sys.exit("usage: python tools/apply_sql.py FILE.sql [FILE.sql ...]")
    conn = psycopg2.connect(url)
    conn.autocommit = True   # files manage their own BEGIN/COMMIT
    try:
        cur = conn.cursor()
        for path in paths:
            with open(path, encoding="utf-8") as f:
                sql = f.read()
            print(f"[apply_sql] applying {path} ...", flush=True)
            cur.execute(sql)
            print(f"[apply_sql] done: {path}", flush=True)
        try:
            cur.execute("SELECT company_type, listing_status, COUNT(*) FROM companies "
                        "GROUP BY 1, 2 ORDER BY 1, 2")
            for row in cur.fetchall():
                print(f"[apply_sql] companies {row[0]} / {row[1]}: {row[2]}", flush=True)
            cur.execute("SELECT COUNT(*) FROM companies WHERE careers_url IS NOT NULL")
            print(f"[apply_sql] careers_url overrides: {cur.fetchone()[0]}", flush=True)
        except Exception as e:
            print(f"[apply_sql] (summary query skipped: {e})", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1:])
