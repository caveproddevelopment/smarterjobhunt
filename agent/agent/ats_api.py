"""
ATS API — fetches job listings from the public APIs of
Greenhouse, Lever, Ashby, and Workable.

Each function returns a list of dicts with normalized keys:
  {
    "title":       str,
    "department":  str,
    "location":    str,
    "apply_url":   str,
    "posted_at":   str,   # ISO date string or empty
  }
"""

import requests
from datetime import datetime
from typing import Optional

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ─────────────────────────────────────────────────────────────────────────────
# Public dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def fetch_jobs(ats: str, token: str) -> list[dict]:
    """Fetch all open jobs from the given ATS."""
    fn = {
        "greenhouse": _fetch_greenhouse,
        "lever":      _fetch_lever,
        "ashby":      _fetch_ashby,
        "workable":   _fetch_workable,
    }.get(ats)

    if fn is None:
        return []

    try:
        return fn(token)
    except Exception as e:
        print(f"[ats_api] Error fetching from {ats}/{token}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_greenhouse(token: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data.get("jobs", []):
        dept = ""
        if j.get("departments"):
            dept = j["departments"][0].get("name", "")

        loc = ""
        if j.get("offices"):
            loc = j["offices"][0].get("name", "")
        elif j.get("location"):
            loc = j["location"].get("name", "")

        jobs.append({
            "title":      j.get("title", ""),
            "department": dept,
            "location":   loc,
            "apply_url":  j.get("absolute_url", ""),
            "posted_at":  _parse_ts(j.get("updated_at", "")),
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Lever
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_lever(token: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data:
        cats = j.get("categories", {})
        apply_url = j.get("applyUrl") or j.get("hostedUrl", "")

        jobs.append({
            "title":      j.get("text", ""),
            "department": cats.get("department", cats.get("team", "")),
            "location":   cats.get("location", cats.get("allLocations", [""])[0] if cats.get("allLocations") else ""),
            "apply_url":  apply_url,
            "posted_at":  _parse_ts_ms(j.get("createdAt", 0)),
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Ashby
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_ashby(token: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data.get("jobPostings", []):
        loc = ""
        if j.get("locationName"):
            loc = j["locationName"]
        elif j.get("isRemote"):
            loc = "Remote"

        jobs.append({
            "title":      j.get("title", ""),
            "department": j.get("departmentName", ""),
            "location":   loc,
            "apply_url":  j.get("jobUrl", ""),
            "posted_at":  j.get("publishedDate", ""),
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Workable
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_workable(token: str) -> list[dict]:
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
    r = requests.post(url, json={"query": "", "location": [], "department": [], "worktype": [], "remote": []},
                      headers={**HEADERS, "Content-Type": "application/json"}, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data.get("results", []):
        jobs.append({
            "title":      j.get("title", ""),
            "department": j.get("department", ""),
            "location":   j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
            "apply_url":  f"https://apply.workable.com/{token}/j/{j.get('shortcode', '')}",
            "posted_at":  j.get("published", ""),
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(ts_str: str) -> str:
    """Parse ISO timestamp string to YYYY-MM-DD."""
    if not ts_str:
        return ""
    try:
        return ts_str[:10]
    except Exception:
        return ""


def _parse_ts_ms(ts_ms: int) -> str:
    """Parse Unix milliseconds to YYYY-MM-DD."""
    if not ts_ms:
        return ""
    try:
        return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""
