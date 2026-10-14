"""
Company Source — where the list of companies to scrape comes from.

Two real sources today:
  - CSVCompanySource: reads the Organization Name / Homepage URL / Last
    Funding Type / Last Funding Amount / Last Funding Date CSV format.
    Used by seed_companies.py and for local smoke tests
    (run_ingestion.py) — never by the Railway cron job.
  - PostgresCompanySource: reads from the `companies` table (seeded by
    seed_companies.py). This is what run_ingestion_db.py uses in
    production.

ingestion_orchestrator.py only ever calls `.load()` and gets back the
same list[dict] shape either way.

Normalized company dict shape:
  {
    "company_name":   str,
    "website":        str,
    "funding_round":  str,   # "Series A" / "Series B"
    "funding_amount": str,   # e.g. "$25,000,000"
    "funding_date":   str,   # ISO YYYY-MM-DD
  }
"""

import csv
import datetime
from abc import ABC, abstractmethod
from typing import Optional

# Different company-list exports use slightly different column names for
# the same field (e.g. india_companies_with_homepages.csv uses "Company
# Homepage URL" instead of "Homepage URL"). Try each candidate in order
# instead of hard-failing to blank on the first mismatch.
_NAME_COLUMNS = ("Organization Name", "Company Name", "Name")
_HOMEPAGE_COLUMNS = ("Homepage URL", "Company Homepage URL", "Website", "Website URL")


def _first_present(row: dict, candidates: tuple[str, ...]) -> str:
    for col in candidates:
        val = row.get(col)
        if val and val.strip():
            return val.strip()
    return ""


class CompanySource(ABC):
    @abstractmethod
    def load(self) -> list[dict]:
        """Return a list of normalized company dicts."""
        raise NotImplementedError


class CSVCompanySource(CompanySource):
    """Reads the company CSV format established for MyJobHunt / the
    100/200/500 batch-size test files:
    Organization Name, Homepage URL, Last Funding Type, Last Funding Amount, Last Funding Date

    Also tolerates the header variants in _NAME_COLUMNS / _HOMEPAGE_COLUMNS
    (e.g. india_companies_with_homepages.csv's "Company Homepage URL").
    """

    def __init__(self, path: str, limit: Optional[int] = None):
        self.path = path
        self.limit = limit

    def load(self) -> list[dict]:
        companies = []
        with open(self.path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = _first_present(row, _NAME_COLUMNS)
                if not name:
                    continue  # skip blank rows
                companies.append({
                    "company_name":  name,
                    "website":       _first_present(row, _HOMEPAGE_COLUMNS),
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
    of a CSV. This is what run_ingestion_db.py uses on Railway.

    Table (as written by seed_companies.py):
        companies(name, website, funding_stage, funding_amount,
                   funding_date, company_type)
        UNIQUE constraint on `name` (upserted by seed_companies.py).

    `limit`, when given, only loads the first N companies (ordered by
    name) — same purpose as CSVCompanySource's limit, for smoke tests
    against a subset before a full run.

    `company_type`, when given, restricts the load to companies tagged
    with that type ('funded' / 'fortune500' / 'indianmajor' — same
    values seed_companies.py's --company-type accepts). Omit it
    (default None) to scrape every company regardless of type, same
    as the previous behavior.

    `names`, when given, restricts the load to companies whose `name`
    exactly matches one of the given strings (case-sensitive, must
    match what's stored in the `name` column). Intended for scoped
    reruns — e.g. retrying only the companies that hard-timed-out on a
    previous run — without needing a whole company_type bucket or a
    positional --limit. Combines with company_type via AND if both are
    given. Names with no matching row are silently skipped, not errored.
    """

    def __init__(self, connection, limit: Optional[int] = None, company_type: Optional[str] = None,
                 names: Optional[list[str]] = None, listing_statuses: Optional[list[str]] = None):
        self.connection = connection
        self.limit = limit
        self.company_type = normalize_company_type(company_type)
        self.names = names
        # Which companies.listing_status values to scrape (2026-10-13, see
        # db/migrations/2026-10-13_listing_status.sql). Default: only
        # 'active'. Ignored if the column doesn't exist yet, so the agent
        # still runs against a database that hasn't been migrated.
        self.listing_statuses = listing_statuses or ["active"]
        self.skipped_by_status = 0

    def _has_listing_status(self) -> bool:
        return self._has_column("listing_status")

    def _has_column(self, column: str) -> bool:
        cur = self.connection.cursor()
        try:
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'companies' AND column_name = %s""", (column,))
            return cur.fetchone() is not None
        except Exception:
            self.connection.rollback()
            return False
        finally:
            cur.close()

    def load(self) -> list[dict]:
        has_override = self._has_column("careers_url")
        # backend/db/schema.sql drops the legacy funding_* columns; read
        # them only if this database still has them.
        funding_cols = ", ".join(c if self._has_column(c) else "NULL"
                                 for c in ("funding_stage", "funding_amount", "funding_date"))
        query = ("SELECT name, website, " + funding_cols
                 + (", careers_url" if has_override else ", NULL") + " FROM companies")
        params: list = []
        clauses: list = []
        status_filter = self._has_listing_status() and "all" not in self.listing_statuses
        if status_filter:
            clauses.append("COALESCE(listing_status, 'active') = ANY(%s)")
            params.append(list(self.listing_statuses))
        if self.company_type:
            clauses.append("company_type = ANY(%s)")
            params.append(company_type_db_values(self.company_type))
        if self.names:
            clauses.append("name = ANY(%s)")
            params.append(self.names)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY name"
        if self.limit:
            query += " LIMIT %s"
            params.append(self.limit)

        cur = self.connection.cursor()
        try:
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
        finally:
            cur.close()

        if status_filter:
            cur = self.connection.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM companies WHERE NOT (COALESCE(listing_status, 'active') = ANY(%s))"
                            + (" AND company_type = ANY(%s)" if self.company_type else ""),
                            tuple([list(self.listing_statuses)]
                                  + ([company_type_db_values(self.company_type)] if self.company_type else [])))
                self.skipped_by_status = cur.fetchone()[0]
            except Exception:
                self.connection.rollback()
            finally:
                cur.close()

        companies = []
        for name, website, funding_stage, funding_amount, funding_date, careers_url in rows:
            companies.append({
                "company_name":  name or "",
                "website":       website or "",
                "funding_round": funding_stage or "",
                "funding_amount": funding_amount or "",
                "funding_date":  _to_iso_str(funding_date),
                # Optional manual override (companies.careers_url, added by
                # db/migrations/2026-10-13_listing_status.sql): tried first.
                "careers_url":   careers_url or "",
            })
        return companies


# The DB CHECK constraint (backend db/schema.sql) allows 'midmarket'; the
# agent's CLI used to offer 'midsize', which matches no row and fails the
# CHECK on seeding. Accept both, store/query 'midmarket'.
_COMPANY_TYPE_ALIASES = {"midsize": "midmarket"}
COMPANY_TYPES = ("funded", "fortune500", "indianmajor", "midmarket", "healthcare")


def normalize_company_type(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    return _COMPANY_TYPE_ALIASES.get(value, value)


def company_type_db_values(value: str) -> list[str]:
    """Values to match in companies.company_type. Production rows seeded
    before 2026-10-13 are tagged 'midsize' (the old CLI value), newer ones
    'midmarket', so either name selects both."""
    if value in ("midsize", "midmarket"):
        return ["midmarket", "midsize"]
    return [value]


def _to_iso_str(value) -> str:
    """funding_date may come back as a date/datetime object depending
    on the column type — normalize it to the ISO string shape every
    other CompanySource returns, so downstream code never has to care."""
    if value is None:
        return ""
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    return str(value)