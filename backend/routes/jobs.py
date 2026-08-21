import re

from flask import Blueprint, g, jsonify, request

from auth_utils import optional_auth
from db.connection import get_cursor

bp = Blueprint("jobs", __name__, url_prefix="/api")

FUNDING_FILTER_MAP = {"a": "series_a", "b": "series_b"}  # 'both' applies no filter

# The backend's list of real Company Database categories (distinct from the
# 'both' filter value, which means "no restriction" rather than being a
# category itself). Kept in sync BY HAND with two other places, since Python
# and the frontend's JS can't share this literal directly:
#   - the CHECK (company_type IN (...)) constraints on companies.company_type
#     and saved_searches.company_type in db/schema.sql
#   - COMPANY_TYPES in frontend/src/lib/companyTypes.js
# Unknown values here are silently ignored (see the `if company_type in
# COMPANY_TYPES` checks below) rather than raising an error, so it's easy to
# forget this one when adding a database -- the symptom is the new filter
# quietly doing nothing instead of a visible failure.
COMPANY_TYPES = {"funded", "fortune500"}

# A job card needs at least a department OR a location to be worth showing.
# Scraped rows sometimes store an empty string ('') rather than a true SQL
# NULL for a missing field, so NULLIF(col, '') normalizes both cases to NULL
# before the IS NOT NULL check -- '' and NULL are treated identically here.
# Reused verbatim in three places (list_jobs, company_jobs, and
# company_type_counts) so the sidebar counts and both job-listing endpoints
# always agree on which jobs are "displayable".
HAS_DEPT_OR_LOCATION = "(NULLIF(j.department, '') IS NOT NULL OR NULLIF(j.location, '') IS NOT NULL)"


def _tokenize_title(title):
    """Split a search title into whitespace-separated terms for word-overlap
    scoring. e.g. "Senior Project Manager" -> ["Senior", "Project", "Manager"].
    """
    return [t for t in title.split() if t]


def _word_boundary_pattern(term):
    """Build a Postgres word-boundary regex (\\y...\\y) for a single term,
    escaping any regex metacharacters in the term itself first so terms like
    "C++" or "UX/UI" are matched literally rather than as regex syntax. \\y
    (not a bare substring) avoids short terms like "PM" false-positive
    matching inside an unrelated word.
    """
    return r"\y" + re.escape(term) + r"\y"


def _description_boost_expr(terms):
    if not terms:
        return None, []
    percent_per_term = 100.0 / len(terms)
    score_terms = []
    params = []
    for term in terms:
        score_terms.append(
            f"(CASE WHEN j.raw_text ~* %s THEN {percent_per_term} ELSE 0 END)"
        )
        params.append(_word_boundary_pattern(term))
    return "(" + " + ".join(score_terms) + ")", params


def _title_score_expr(terms):
    if not terms:
        return None, []
    percent_per_term = 100.0 / len(terms)
    score_terms = []
    params = []
    for term in terms:
        score_terms.append(
            f"(CASE WHEN j.title ~* %s THEN {percent_per_term} ELSE 0 END)"
        )
        params.append(_word_boundary_pattern(term))
    return "(" + " + ".join(score_terms) + ")", params


def _combine_match_percent(title_expr, title_params, desc_expr, desc_params):
    if title_expr is None:
        return None, []
    combined = (
        f"ROUND(CASE WHEN ({title_expr}) > 0 "
        f"THEN ({title_expr}) ELSE ({desc_expr}) END)::int"
    )
    return combined, [*title_params, *title_params, *desc_params]


@bp.get("/jobs")
@optional_auth
def list_jobs():
    title = request.args.get("title", "").strip()
    variant_titles = [v.strip() for v in request.args.getlist("variant_title") if v.strip()]
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()
    company_type = request.args.get("company_type", "both").strip().lower()
    company_id = request.args.get("company_id", "").strip()
    status_filter = request.args.get("status", "").strip().lower()
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    where = []
    params = []

    terms = _tokenize_title(title) if title else []

    desc_score_expr, desc_score_params = _description_boost_expr(terms)
    title_score_expr, title_score_params = _title_score_expr(terms)
    search_match_expr, search_match_params = _combine_match_percent(
        title_score_expr, title_score_params, desc_score_expr, desc_score_params
    )

    if status_filter not in {"applied", "rejected", "tracked"}:
        where.append("j.is_active = true")

    # Data-quality guard: a job scraped with NEITHER a department nor a
    # location is missing too much to render a useful card -- exclude it.
    # A job with only one of the two still has something to show, so this
    # only drops rows where both are missing (not either/or). Treats an
    # empty string the same as a true NULL (see HAS_DEPT_OR_LOCATION).
    where.append(HAS_DEPT_OR_LOCATION)

    if title or variant_titles:
        title_matches = []
        for candidate in [title, *variant_titles]:
            if candidate:
                title_matches.append("j.title ILIKE %s")
                params.append(f"%{candidate}%")

        if title_score_expr:
            title_matches.append(f"(({title_score_expr}) > 0)")
            params.extend(title_score_params)

        if desc_score_expr:
            title_matches.append(f"(({desc_score_expr}) >= 50)")
            params.extend(desc_score_params)

        where.append("(" + " OR ".join(title_matches) + ")")

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    if company_type in COMPANY_TYPES:
        where.append("c.company_type = %s")
        params.append(company_type)

    if company_id:
        where.append("c.id = %s")
        params.append(int(company_id))

    if status_filter == "applied":
        where.append("s.status = 'applied'")
    elif status_filter == "rejected":
        where.append("s.status = 'rejected'")
    elif status_filter == "tracked":
        where.append("s.status IS NOT NULL")

    where_clause = " AND ".join(where) if where else "true"

    order_by_boost = desc_score_expr if desc_score_expr is not None else "0::numeric"

    count_query = f"""
        SELECT count(*)
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN user_job_status s ON s.job_id = j.id AND s.user_id = %s
        WHERE {where_clause}
    """
    cur = get_cursor()
    cur.execute(count_query, [g.user_id, *params])
    total_count = cur.fetchone()["count"]

    query = f"""
        SELECT
            j.id,
            j.title,
            j.department,
            j.location,
            j.date_posted,
            j.source_url,
            c.id AS company_id,
            c.name AS company,
            c.website AS company_website,
            c.funding_stage AS funding,
            c.company_type AS company_type,
            (
                SELECT count(*) FROM jobs j2
                WHERE j2.company_id = c.id AND j2.is_active AND j2.id != j.id
            ) AS other_jobs_at_company,
            m.match_percent AS match,
            {search_match_expr if search_match_expr is not None else 'NULL'} AS search_match_percent,
            s.status,
            s.reason_rejected
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        LEFT JOIN user_job_status s ON s.job_id = j.id AND s.user_id = %s
        WHERE {where_clause}
        ORDER BY m.match_percent DESC NULLS LAST, {order_by_boost} DESC, j.date_posted DESC
        LIMIT %s OFFSET %s
    """
    full_params = [
        *search_match_params,
        g.user_id,
        g.user_id,
        *params,
        *desc_score_params,
        limit,
        offset,
    ]

    cur.execute(query, full_params)
    jobs = cur.fetchall()

    return jsonify({"jobs": jobs, "count": len(jobs), "total_count": total_count})


@bp.get("/jobs/variant-counts")
@optional_auth
def variant_counts():
    variant_titles = [v.strip() for v in request.args.getlist("variant_title") if v.strip()]
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()
    company_type = request.args.get("company_type", "both").strip().lower()

    if not variant_titles:
        return jsonify({"counts": {}})

    where = ["j.is_active = true", "j.title ILIKE '%%' || v.title || '%%'"]
    params = []

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    if company_type in COMPANY_TYPES:
        where.append("c.company_type = %s")
        params.append(company_type)

    where_clause = " AND ".join(where)

    query = f"""
        SELECT
            v.title AS variant_title,
            (
                SELECT count(*)
                FROM jobs j
                JOIN companies c ON c.id = j.company_id
                WHERE {where_clause}
            ) AS job_count
        FROM unnest(%s::text[]) WITH ORDINALITY AS v(title, ord)
        ORDER BY v.ord
    """
    full_params = [*params, variant_titles]

    cur = get_cursor()
    cur.execute(query, full_params)
    rows = cur.fetchall()

    counts = {row["variant_title"]: row["job_count"] for row in rows}
    return jsonify({"counts": counts})


@bp.get("/jobs/company-type-counts")
@optional_auth
def company_type_counts():
    cur = get_cursor()
    cur.execute(
        f"""
        SELECT c.company_type, count(*) AS job_count
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.is_active = true
          AND {HAS_DEPT_OR_LOCATION}
        GROUP BY c.company_type
        """
    )
    rows = cur.fetchall()

    counts = {"funded": 0, "fortune500": 0}
    for row in rows:
        if row["company_type"] in counts:
            counts[row["company_type"]] = row["job_count"]
    counts["both"] = counts["funded"] + counts["fortune500"]

    return jsonify({"counts": counts})


@bp.get("/companies/<int:company_id>/jobs")
@optional_auth
def company_jobs(company_id):
    cur = get_cursor()
    cur.execute(
        f"""
        SELECT
            j.id, j.title, j.department, j.location, j.date_posted,
            m.match_percent AS match
        FROM jobs j
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        WHERE j.company_id = %s AND j.is_active = true
          AND {HAS_DEPT_OR_LOCATION}
        ORDER BY j.date_posted DESC
        """,
        (g.user_id, company_id),
    )
    return jsonify({"jobs": cur.fetchall()})