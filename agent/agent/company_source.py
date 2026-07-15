"""
Company Source — where the list of companies to scrape comes from.

This is the swap point called out in the SJH.com proof-of-concept plan:
today it's a CSV file (the same Organization Name / Homepage URL / Last
Funding Type / Last Funding Amount / Last Funding Date format used in
MyJobHunt's company lists). In production this is `PostgresCompanySource`,
reading from the `companies` table. Nothing else in the ingestion
pipeline needs to change when that swap happens — ingestion_orchestrator.py
only ever calls `.load()` and gets back the same list[dict] shape either way.

Normalized company dict shape:
  {
    "company_name":   str,
    "website":        str,
    "funding_round":  str,   # "Series A" / "Series B"
    "funding_amount":  str,   # e.g. "$25,000,000"
    "funding_date":   str,   # ISO YYYY-MM-DD
  }
"""

import csv
from abc import ABC, abstractmethod
from typing import Optional


class CompanySource(ABC):
    @abstractmethod
    def load(self) -> list[dict]:
        """Return a list of normalized company dicts."""
        raise NotImplementedError


class CSVCompanySource(CompanySource):
    """Reads the company CSV format established for MyJobHunt / the
    100/200/500 batch-size test files:
    Organization Name, Homepage URL, Last Funding Type, Last Funding Amount, Last Funding Date
    """

    def __init__(self, path: str, limit: Optional[int] = None):
        self.path = path
        self.limit = limit

    def load(self) -> list[dict]:
        companies = []
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("Organization Name") or "").strip()
                if not name:
                    continue  # skip blank rows
                companies.append({
                    "company_name":  name,
                    "website":       (row.get("Homepage URL") or "").strip(),
                    "funding_round": (row.get("Last Funding Type") or "").strip(),
                    "funding_amount": (row.get("Last Funding Amount") or "").strip(),
                    "funding_date":  (row.get("Last Funding Date") or "").strip(),
                })
                if self.limit and len(companies) >= self.limit:
                    break
        return companies


class PostgresCompanySource(CompanySource):
    """
    Reads the company list from the Postgres `companies` table instead
    of a CSV. This is what the scheduled Railway ingestion run uses —
    the CSV is only needed once, to seed `companies` (see
    seed_companies.py), after that the DB is the source of truth: add,
    edit, or remove companies there and the next scrape picks it up.

    `connection` is any psycopg2 connection (e.g. from
    `psycopg2.connect(os.environ["DATABASE_URL"])`).
    """

    _FUNDING_STAGE_LABELS = {
        "seed": "Seed",
        "series_a": "Series A",
        "series_b": "Series B",
        "series_c_plus": "Series C+",
        "public": "Public",
        "bootstrapped": "Bootstrapped",
        "unknown": "",
    }

    def __init__(self, connection, limit: Optional[int] = None):
        self.connection = connection
        self.limit = limit

    def load(self) -> list[dict]:
        cur = self.connection.cursor()
        try:
            query = "SELECT name, website, funding_stage, funding_amount, funding_date FROM companies ORDER BY id"
            if self.limit:
                query += " LIMIT %s"
                cur.execute(query, (self.limit,))
            else:
                cur.execute(query)

            companies = []
            for name, website, funding_stage, funding_amount, funding_date in cur.fetchall():
                companies.append({
                    "company_name": name,
                    "website": website or "",
                    "funding_round": self._FUNDING_STAGE_LABELS.get(funding_stage, ""),
                    "funding_amount": funding_amount or "",
                    "funding_date": funding_date.isoformat() if funding_date else "",
                })
            return companies
        finally:
            cur.close()
