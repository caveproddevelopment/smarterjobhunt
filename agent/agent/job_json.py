"""
Job JSON harvesting — pull job listings out of the JSON responses a careers
page loads while it renders.

Why: most Indian hiring platforms in the 7 Oct findings (Darwinbox, Keka,
PeopleStrong, SenseHQ, Zoho Recruit, Kula, TurboHire, Param, ...) are
JavaScript apps. Their job lists often aren't plain <a href> links (click
handlers, router links), so the link scraper sees "no links" or only nav
junk. But every one of them fetches its jobs as JSON. The scraper records
the JSON responses (async_career_scraper.py) and this module finds the job
array inside them, whatever the platform calls its fields.

Pure functions only — unit-testable without a browser.
"""

import re
from typing import Any, Optional
from urllib.parse import urljoin, quote

from .text_extract import make_snippet

TITLE_KEYS = ("title", "jobTitle", "job_title", "Title", "JobTitle", "designation", "postingTitle",
              "Posting_Title", "positionName", "position_name", "position", "requisitionTitle",
              "jobName", "job_name", "displayName", "name", "role", "roleName", "opening_name")
URL_KEYS = ("jobUrl", "job_url", "applyUrl", "apply_url", "absolute_url", "hostedUrl", "url", "link",
            "href", "externalUrl", "careers_url", "detailUrl", "detail_url", "job_link", "jobLink",
            "publicUrl", "public_url", "shareUrl", "share_url", "permalink", "externalPath", "jobPath")
ID_KEYS = ("id", "jobId", "job_id", "Id", "ID", "requisitionId", "requisition_id", "reqId", "jobCode",
           "job_code", "shortcode", "uuid", "slug", "code", "jobOpeningId", "openingId", "posting_id",
           "_id", "job_uuid")
LOC_KEYS = ("location", "locationName", "location_name", "locationsText", "locations", "city", "job_location",
            "jobLocation", "Location", "officeLocation", "PrimaryLocation", "work_location", "workLocation",
            "cities", "office")
DEPT_KEYS = ("department", "departmentName", "department_name", "team", "function", "Department",
             "category", "job_category", "jobCategory", "businessUnit", "business_unit", "dept", "division")
DATE_KEYS = ("postedOn", "publishedAt", "published_at", "createdAt", "created_at", "postedDate", "PostedDate",
             "datePosted", "date_posted", "publishedDate", "releasedDate", "released_date", "posted_at",
             "postingDate", "openDate", "updated_at", "updatedAt")
DESC_KEYS = ("description", "descriptionHtml", "descriptionPlain", "jobDescription", "job_description",
             "JobDescription", "summary", "ShortDescriptionStr", "details", "about", "responsibilities",
             "job_summary", "jd", "jobDetails")

# Keys that, alongside a title, say "this object is a job, not a blog post".
JOBISH_KEYS = {k.lower() for k in (
    *LOC_KEYS, *DEPT_KEYS, "experience", "minExperience", "maxExperience", "min_experience", "exp",
    "employmentType", "employment_type", "jobType", "job_type", "workType", "work_type", "workplaceType",
    "salary", "salaryRange", "ctc", "requisition", "requisitionId", "openings", "no_of_openings",
    "vacancies", "positions", "skills", "jobCode", "job_code", "isRemote", "remote", "applyUrl",
    "apply_url", "postedOn", "datePosted", "closingDate", "closing_date", "hiringManager", "jobId", "job_id",
    "qualification", "qualifications", "seniority", "level", "grade", "shift",
)}

_JOBBY_URL = re.compile(r"job|career|requisition|opening|position|vacanc|posting|recruit|hiring|candidate", re.I)
_MAX_DEPTH = 7


def _first_str(d: dict, keys) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (str, int, float)) and not isinstance(v, bool) and str(v).strip():
            return str(v).strip()
    return ""


def _stringify(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return str(v)
    if isinstance(v, dict):
        for k in ("name", "label", "city", "title", "value", "displayName", "text", "location_name"):
            if isinstance(v.get(k), str) and v[k].strip():
                return v[k].strip()
        return ""
    if isinstance(v, list):
        parts = [_stringify(x) for x in v[:3]]
        return ", ".join(p for p in parts if p)
    return ""


def _first_val(d: dict, keys) -> str:
    for k in keys:
        if k in d:
            s = _stringify(d[k])
            if s:
                return s
    return ""


_WEAK_TITLE_KEYS = {"name", "role", "position", "displayName", "roleName"}
_LOC_LOWER = {k.lower() for k in LOC_KEYS}


def _title_key(d: dict) -> Optional[str]:
    for k in TITLE_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return k
    return None


def _looks_like_job(d: dict) -> bool:
    if not isinstance(d, dict):
        return False
    tk = _title_key(d)
    if not tk:
        return False
    title = d[tk].strip()
    if len(title) < 3 or len(title) > 150:
        return False
    keys = {k.lower() for k in d.keys()} - {tk.lower()}
    jobish = keys & JOBISH_KEYS
    if tk in _WEAK_TITLE_KEYS:
        # {"name": "Bengaluru", "city": ...} is a location facet, not a job:
        # with a generic title key, demand two job-ish fields, one of them
        # not a location field.
        return len(jobish) >= 2 and bool(jobish - _LOC_LOWER)
    return len(jobish) >= 1


def _candidate_lists(obj: Any, depth: int = 0):
    """Yield every list of dicts inside obj (depth-limited)."""
    if depth > _MAX_DEPTH:
        return
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) for x in obj[:20]):
            yield obj
        for x in obj[:200]:
            if isinstance(x, (dict, list)):
                yield from _candidate_lists(x, depth + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, (dict, list)):
                yield from _candidate_lists(v, depth + 1)


def _jobs_from_list(items: list, page_url: str, api_url: str) -> list[dict]:
    jobs, seen = [], set()
    for d in items:
        if not _looks_like_job(d):
            continue
        title = _first_str(d, TITLE_KEYS)
        url = _first_str(d, URL_KEYS)
        jid = _first_str(d, ID_KEYS)
        if url and not url.startswith(("http://", "https://")):
            if url.startswith(("/", "./", "../")) or "/" in url:
                url = urljoin(page_url, url)
            else:
                url = ""
        if url and url.rstrip("/") == page_url.rstrip("/"):
            url = ""  # a link back to the listing page is not unique per job
        if not url:
            if not jid:
                continue   # nothing unique to dedupe on — skip rather than collapse jobs
            url = page_url.split("#")[0] + "#job-" + quote(jid, safe="")
        if url in seen:
            continue
        seen.add(url)
        desc = ""
        for k in DESC_KEYS:
            v = d.get(k)
            if isinstance(v, str) and len(v.strip()) > 20:
                desc = make_snippet(v, is_html="<" in v)
                break
        jobs.append({
            "title":               re.sub(r"\s+", " ", title),
            "department":          _first_val(d, DEPT_KEYS),
            "location":            _first_val(d, LOC_KEYS),
            "apply_url":           url,
            "posted_at":           _first_str(d, DATE_KEYS)[:10] if re.match(r"\d{4}-\d{2}-\d{2}", _first_str(d, DATE_KEYS)) else "",
            "description_snippet": desc,
        })
    return jobs


def harvest_jobs_from_json(responses: list[tuple[str, Any]], page_url: str,
                           on_platform: bool = False) -> list[dict]:
    """Given [(response_url, parsed_json), ...] captured while a careers page
    loaded, return the best job list found (possibly empty).

    A list qualifies when at least 60% of its objects look like jobs (a
    title plus at least one job-ish field such as location, department,
    experience). To avoid harvesting blog posts or product lists, the JSON
    must come from a job-ish URL, or the page must be a known hiring
    platform, or the list must have 3+ job objects with 2+ job-ish keys each.
    """
    best: list[dict] = []
    for api_url, data in responses:
        jobby_source = on_platform or bool(_JOBBY_URL.search(api_url or ""))
        for lst in _candidate_lists(data):
            sample = lst[:50]
            n_job = sum(1 for d in sample if _looks_like_job(d))
            if n_job == 0 or n_job < 0.6 * len(sample):
                continue
            if not jobby_source:
                strong = sum(1 for d in sample if isinstance(d, dict)
                             and len({k.lower() for k in d} & JOBISH_KEYS) >= 2)
                if strong < 3:
                    continue
            jobs = _jobs_from_list(lst, page_url, api_url)
            if len(jobs) > len(best):
                best = jobs
    return best
