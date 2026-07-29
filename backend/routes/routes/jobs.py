from flask import Blueprint, g, jsonify, request

from auth_utils import optional_auth
from db.connection import get_cursor

bp = Blueprint("jobs", __name__, url_prefix="/api")

FUNDING_FILTER_MAP = {"a": "series_a", "b": "series_b"}  # 'both' applies no filter


@bp.get("/jobs")
@optional_auth
def list_jobs():
    title = request.args.get("title", "").strip()
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))
    # 'variants' is accepted for forward-compatibility with the scraping agent
    # (it controls how many close title variants get scraped) but doesn't filter here yet.

    where = ["j.is_active = true"]
    params = []

    if title:
        where.append("j.title ILIKE %s")
        params.append(f"%{title}%")

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
            c.id AS company_id,
            c.name AS company,
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