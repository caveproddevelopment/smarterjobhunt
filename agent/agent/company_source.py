"""
Company Source — where the list of companies to scrape comes from.

This is the swap point called out in the SJH.com proof-of-concept plan:
today it's a CSV file (the same Organization Name / Homepage URL / Last
Funding Type / Last Funding Amount / Last Funding Date format used in
MyJobHunt's company lists). Later, this becomes a MySQL query. Nothing
else in the ingestion pipeline needs to change when that swap happens —
ingestion_orchestrator.py only ever calls `.load()` and gets back the
same list[dict] shape either way.

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


class MySQLCompanySource(CompanySource):
    """
    PLANNED — not yet implemented. Will query the `companies` table
    instead of reading a CSV. Left as a stub so the interface is visible
    now and the swap later is a one-file change, not a redesign.

    Expected eventual shape:
        SELECT company_name, website, funding_round, funding_amount, funding_date
        FROM companies
        WHERE <scrape-cadence filter, e.g. last_scraped_at IS NULL OR last_scraped_at < ...>
    """

    def __init__(self, connection, query: Optional[str] = None):
        self.connection = connection
        self.query = query

    def load(self) -> list[dict]:
        raise NotImplementedError(
            "MySQLCompanySource is a planned stub — SJH.com will implement this "
            "once the company DB schema is finalized. Use CSVCompanySource for now."
        )
