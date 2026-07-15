#!/usr/bin/env python3
"""
SJH.com Ingestion Agent — proof of concept.

Usage:
    python run_ingestion.py --input sjh_companies_100.csv --output jobs_100.csv
    python run_ingestion.py --input sjh_companies_500.csv --output jobs_500.csv --max-workers 15

Also writes a companion `<output>.timing.csv` — per-company path
(ats_api / career_scrape / error) and elapsed seconds, which is exactly
what's needed to model how ingestion time scales past 500 companies
toward SJH.com's 1000+ target (see the batch-size speed test plan).
"""

import argparse
import csv
import time
import sys

from agent.company_source import CSVCompanySource
from agent.job_sink import CSVJobSink
from agent.ingestion_orchestrator import run


def main():
    parser = argparse.ArgumentParser(description="SJH.com job ingestion agent (proof of concept)")
    parser.add_argument("--input", required=True, help="Path to company CSV (Organization Name, Homepage URL, Last Funding Type, Last Funding Amount, Last Funding Date)")
    parser.add_argument("--output", required=True, help="Path to write scraped job listings CSV")
    parser.add_argument("--max-workers", type=int, default=10, help="Concurrent companies to process (default 10)")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N companies (for quick smoke tests)")
    args = parser.parse_args()

    source = CSVCompanySource(args.input, limit=args.limit)
    sink = CSVJobSink(args.output)

    def progress(pct, msg):
        print(f"[{int(pct*100):3d}%] {msg}", flush=True)

    start = time.time()
    summary = run(source, sink, max_workers=args.max_workers, progress_callback=progress)
    total_elapsed = time.time() - start

    timing_path = args.output.rsplit(".", 1)[0] + ".timing.csv"
    with open(timing_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["company_name", "path", "elapsed_seconds", "jobs_found"])
        writer.writeheader()
        writer.writerows(summary["per_company_timing"])

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
    print(f"\nJob listings written to: {args.output}")
    print(f"Per-company timing log:  {timing_path}")


if __name__ == "__main__":
    sys.exit(main())
