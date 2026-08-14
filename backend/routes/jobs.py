from flask import Blueprint, g, jsonify, request

from auth_utils import optional_auth
from db.connection import get_cursor

bp = Blueprint("jobs", __name__, url_prefix="/api")

FUNDING_FILTER_MAP = {"a": "series_a", "b": "series_b"}  # 'both' applies no filter


@bp.get("/jobs")
@optional_auth
def list_jobs():
    title = request.args.get("title", "").strip()
    variant_titles = [v.strip() for v in request.args.getlist("variant_title") if v.strip()]
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    where = ["j.is_active = true"]
    params = []

    # Title + its variants are OR'd together as one group (any of them can
    # match), then AND'd with the other filters below. The frontend always
    # sends up to the full 15 cached/generated variants for the title (the
    # variants count is fixed, not user-selectable).
    if title or variant_titles:
        title_matches = []
        for candidate in [title, *variant_titles]:
            if candidate:
                title_matches.append("j.title ILIKE %s")
                params.append(f"%{candidate}%")
        where.append("(" + " OR ".join(title_matches) + ")")

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    where_clause = " AND ".join(where)

    count_query = f"""
        SELECT count(*)
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE {where_clause}
    """
    cur = get_cursor()
    cur.execute(count_query, params)
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
            (
                SELECT count(*) FROM jobs j2
                WHERE j2.company_id = c.id AND j2.is_active AND j2.id != j.id
            ) AS other_jobs_at_company,
            m.match_percent AS match,
            s.status,
            s.reason_rejected
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        LEFT JOIN user_job_status s ON s.job_id = j.id AND s.user_id = %s
        WHERE {where_clause}
        ORDER BY m.match_percent DESC NULLS LAST, j.date_posted DESC
        LIMIT %s OFFSET %s
    """
    full_params = [g.user_id, g.user_id, *params, limit, offset]

    cur.execute(query, full_params)
    jobs = cur.fetchall()

    return jsonify({"jobs": jobs, "count": len(jobs), "total_count": total_count})


@bp.get("/jobs/variant-counts")
@optional_auth
def variant_counts():
    """How many active jobs match each of the given title variants, one at a
    time -- e.g. {"Product Owner": 4, "Senior Product Manager": 0, ...}.
    Powers the clickable "Also matching" pills: a variant with a count of 0
    isn't worth letting someone click into. Each variant is counted on its
    own (never OR'd with the others or with the main title), since a click
    on a pill should show ONLY that variant's jobs. posted_days/funding are
    accepted so the counts match whatever's currently applied everywhere
    else on the page.
    """
    variant_titles = [v.strip() for v in request.args.getlist("variant_title") if v.strip()]
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()

    if not variant_titles:
        return jsonify({"counts": {}})

    # Note the doubled %% -- these are literal wildcard characters sitting
    # in the query text itself (not a bound parameter), and psycopg2 treats
    # a bare % in the query as the start of a %s/%(name)s placeholder once
    # any parameters are being passed, so it must be escaped.
    where = ["j.is_active = true", "j.title ILIKE '%%' || v.title || '%%'"]
    params = []

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    where_clause = " AND ".join(where)

    # A correlated subquery per unnested variant keeps each count
    # independent (no cross-variant double counting) while still costing a
    # single round trip to the DB for all 15 variants.
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


@bp.get("/companies/<int:company_id>/jobs")
@optional_auth
def company_jobs(company_id):
    cur = get_cursor()
    cur.execute(
        """
        SELECT
            j.id, j.title, j.department, j.location, j.date_posted,
            m.match_percent AS match
        FROM jobs j
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        WHERE j.company_id = %s AND j.is_active = true
        ORDER BY j.date_posted DESC
        """,
        (g.user_id, company_id),
    )
    return jsonify({"jobs": cur.fetchall()})