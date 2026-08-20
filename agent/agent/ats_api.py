"""
ATS API — fetches job listings from the public APIs of
Greenhouse, Lever, Ashby, and Workable.

Each function returns a list of dicts with normalized keys:
  {
    "title":                 str,
    "department":            str,
    "location":              str,
    "apply_url":             str,
    "posted_at":             str,   # ISO date string or empty
    "description_snippet":   str,   # first N chars of cleaned JD text, see text_extract.py
  }

Description-snippet capture (added 2026-08-19 — see the evaluation in
claude/monte_turner_consolidated_knowledge.md / project chat history):
Greenhouse and Lever's list APIs already return enough of the raw
description in the same response used for titles, so capturing it here
is close to free — no extra request. Ashby and Workable are different:
Ashby's list response may not always include the full description body
(unverified against a live account as of this change — falls back to ""
if the field isn't present rather than guessing a detail-endpoint URL),
and Workable's list endpoint does not include the description at all,
so `_fetch_workable` makes one additional GET per job when
`fetch_descriptions=True`. That's a real cost: N extra requests for a
company with N postings, not a free lookup like Greenhouse/Lever. Set
`fetch_descriptions=False` to skip it entirely (e.g. for a fast smoke
test) — see fetch_jobs()'s docstring.
"""

import requests
from datetime import datetime
from typing import Optional

from .text_extract import make_snippet

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

def fetch_jobs(ats: str, token: str, fetch_descriptions: bool = True) -> list[dict]:
    """Fetch all open jobs from the given ATS.

    `fetch_descriptions`: when True (default), populate description_snippet.
    For Greenhouse/Lever this costs nothing extra (already in the list
    response). For Workable this adds one GET request per job posting —
    set False to skip that cost, e.g. for a quick smoke test or a company
    known to post a very large number of jobs.
    """
    fn = {
        "greenhouse": _fetch_greenhouse,
        "lever":      _fetch_lever,
        "ashby":      _fetch_ashby,
        "workable":   _fetch_workable,
    }.get(ats)

    if fn is None:
        return []

    try:
        return fn(token, fetch_descriptions=fetch_descriptions)
    except Exception as e:
        print(f"[ats_api] Error fetching from {ats}/{token}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Greenhouse
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_greenhouse(token: str, fetch_descriptions: bool = True) -> list[dict]:
    # content=true was already being requested before this change but the
    # returned `content` field (full HTML job description) was being
    # discarded. This is the free case: no extra request needed.
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

        snippet = ""
        if fetch_descriptions:
            snippet = make_snippet(j.get("content", ""), is_html=True)

        jobs.append({
            "title":               j.get("title", ""),
            "department":          dept,
            "location":            loc,
            "apply_url":           j.get("absolute_url", ""),
            "posted_at":           _parse_ts(j.get("updated_at", "")),
            "description_snippet": snippet,
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Lever
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_lever(token: str, fetch_descriptions: bool = True) -> list[dict]:
    # descriptionPlain / description are already in the list response —
    # another free case, no extra request needed.
    url = f"https://api.lever.co/v0/postings/{token}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data:
        cats = j.get("categories", {})
        apply_url = j.get("applyUrl") or j.get("hostedUrl", "")

        snippet = ""
        if fetch_descriptions:
            if j.get("descriptionPlain"):
                snippet = make_snippet(j.get("descriptionPlain", ""), is_html=False)
            else:
                snippet = make_snippet(j.get("description", ""), is_html=True)

        jobs.append({
            "title":               j.get("text", ""),
            "department":          cats.get("department", cats.get("team", "")),
            "location":            cats.get("location", cats.get("allLocations", [""])[0] if cats.get("allLocations") else ""),
            "apply_url":           apply_url,
            "posted_at":           _parse_ts_ms(j.get("createdAt", 0)),
            "description_snippet": snippet,
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Ashby
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_ashby(token: str, fetch_descriptions: bool = True) -> list[dict]:
    # NOT LIVE-VERIFIED: assumes the list response may include
    # descriptionHtml per posting. If a live account shows it does not,
    # this silently falls back to "" rather than guessing a detail-fetch
    # URL — test against a real Ashby-backed company before relying on
    # this field for Ashby postings specifically.
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

        snippet = ""
        if fetch_descriptions:
            snippet = make_snippet(j.get("descriptionHtml", ""), is_html=True)

        jobs.append({
            "title":               j.get("title", ""),
            "department":          j.get("departmentName", ""),
            "location":            loc,
            "apply_url":           j.get("jobUrl", ""),
            "posted_at":           j.get("publishedDate", ""),
            "description_snippet": snippet,
        })

    return jobs


# ─────────────────────────────────────────────────────────────────────────────
# Workable
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_workable(token: str, fetch_descriptions: bool = True) -> list[dict]:
    # NOT the free case: Workable's list/search endpoint does not include
    # the job description body, so fetch_descriptions=True here means one
    # additional GET request per job posting (via _fetch_workable_detail).
    # A company with 50 open Workable postings means 50 extra requests on
    # top of the 1 list request — this is the highest per-job request cost
    # of the four ATS integrations. Consider fetch_descriptions=False for
    # Workable-heavy runs until the cost is measured against a real batch.
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs"
    r = requests.post(url, json={"query": "", "location": [], "department": [], "worktype": [], "remote": []},
                      headers={**HEADERS, "Content-Type": "application/json"}, timeout=15)
    r.raise_for_status()
    data = r.json()

    jobs = []
    for j in data.get("results", []):
        shortcode = j.get("shortcode", "")
        snippet = ""
        if fetch_descriptions and shortcode:
            snippet = _fetch_workable_detail(token, shortcode)

        jobs.append({
            "title":               j.get("title", ""),
            "department":          j.get("department", ""),
            "location":            j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
            "apply_url":           f"https://apply.workable.com/{token}/j/{shortcode}",
            "posted_at":           j.get("published", ""),
            "description_snippet": snippet,
        })

    return jobs


def _fetch_workable_detail(token: str, shortcode: str) -> str:
    """One extra GET per job — see the cost note on _fetch_workable above.
    NOT LIVE-VERIFIED: this URL pattern mirrors Workable's public apply-page
    structure but hasn't been confirmed against a live account. Fails soft
    (returns "") rather than raising, so a wrong endpoint degrades to a
    missing snippet, not a broken run.
    """
    url = f"https://apply.workable.com/api/v3/accounts/{token}/jobs/{shortcode}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return ""
        data = r.json()
        description = data.get("description", "") or data.get("description_html", "")
        return make_snippet(description, is_html=True)
    except Exception:
        return ""


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
