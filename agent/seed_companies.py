#!/usr/bin/env python3
"""
Seed the Postgres `companies` table from a company CSV.

Run this once (or whenever you want to add/refresh the company list) —
after this, PostgresCompanySource reads from the DB, so
run_ingestion_db.py doesn't need the CSV anymore.

Usage:
    export DATABASE_URL=postgresql://user:pass@host:5432/dbname
    python seed_companies.py --input sjh_companies_500.csv

Safe to re-run: upserts by company name (same ON CONFLICT the ingestion
agent uses), so re-seeding just updates funding info rather than
duplicating rows.
"""

import argparse
import os
import sys

import psycopg2

from agent.company_source import CSVCompanySource
from agent.job_sink import _normalize_funding_stage


def main():
    parser = argparse.ArgumentParser(description="Seed/refresh the companies table from a CSV")
    parser.add_argument("--input", required=True, help="Path to company CSV")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    args = parser.parse_args()

    if not args.database_url:
        sys.exit("DATABASE_URL not set (pass --database-url or export the env var)")

    companies = CSVCompanySource(args.input).load()
    print(f"Loaded {len(companies)} companies from {args.input}")

    conn = psycopg2.connect(args.database_url)
    cur = conn.cursor()
    try:
        for c in companies:
            cur.execute(
                """
                INSERT INTO companies (name, website, funding_stage, funding_amount, funding_date)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    website        = EXCLUDED.website,
                    funding_stage  = EXCLUDED.funding_stage,
                    funding_amount = EXCLUDED.funding_amount,
                    funding_date   = EXCLUDED.funding_date
                """,
                (
                    c["company_name"],
                    c["website"] or None,
                    _normalize_funding_stage(c["funding_round"]),
                    c["funding_amount"] or None,
                    c["funding_date"] or None,
                ),
            )
        conn.commit()
        print(f"Seeded/updated {len(companies)} companies in the database.")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
