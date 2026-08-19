import psycopg2
from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("saved_searches", __name__, url_prefix="/api/saved-searches")

VALID_VIEW_TYPES = {"search", "variant", "company", "status"}
VALID_STATUS_FILTERS = {"applied", "rejected"}


@bp.get("")
@require_auth
def list_saved_searches():
    cur = get_cursor()
    cur.execute(
        """
        SELECT
            ss.id, ss.name, ss.view_type, ss.job_title, ss.variant_title,
            ss.posted_within_days, ss.company_type, ss.funding_filter,
            ss.status_filter, ss.company_id, c.name AS company_name,
            ss.created_at
        FROM saved_searches ss
        LEFT JOIN companies c ON c.id = ss.company_id
        WHERE ss.user_id = %s
        ORDER BY ss.created_at DESC
        """,
        (g.user_id,),
    )
    return jsonify({"saved_searches": cur.fetchall()})


@bp.post("")
@require_auth
def create_saved_search():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400

    view_type = (body.get("view_type") or "search").strip().lower()
    if view_type not in VALID_VIEW_TYPES:
        return jsonify({"error": f"view_type must be one of {sorted(VALID_VIEW_TYPES)}"}), 400

    status_filter = body.get("status_filter")
    if status_filter is not None and status_filter not in VALID_STATUS_FILTERS:
        return jsonify({"error": f"status_filter must be one of {sorted(VALID_STATUS_FILTERS)}"}), 400

    cur = get_cursor()
    try:
        cur.execute(
            """
            INSERT INTO saved_searches
                (user_id, name, view_type, job_title, variant_title, variants,
                 posted_within_days, company_type, funding_filter, status_filter,
                 company_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, view_type, job_title, variant_title,
                      posted_within_days, company_type, funding_filter,
                      status_filter, company_id, created_at
            """,
            (
                g.user_id,
                name,
                view_type,
                body.get("job_title"),
                body.get("variant_title"),
                15,  # variants count is no longer user-adjustable — always 15
                body.get("posted_within_days"),
                body.get("company_type", "both"),
                body.get("funding_filter", "both"),
                status_filter,
                body.get("company_id"),
            ),
        )
        saved = cur.fetchone()
        cur.connection.commit()
    except psycopg2.errors.UniqueViolation:
        cur.connection.rollback()
        return jsonify({"error": "You already have this search bookmarked"}), 409

    # The RETURNING clause above can't include the joined company name (it's
    # not a column on this table) -- fetch it separately so the response
    # shape matches the list endpoint's, which the frontend relies on to
    # render "All jobs at <company>" without a follow-up request.
    if saved.get("company_id"):
        cur.execute("SELECT name FROM companies WHERE id = %s", (saved["company_id"],))
        row = cur.fetchone()
        saved["company_name"] = row["name"] if row else None
    else:
        saved["company_name"] = None

    return jsonify(saved), 201


@bp.delete("/<int:search_id>")
@require_auth
def delete_saved_search(search_id):
    cur = get_cursor()
    cur.execute(
        "DELETE FROM saved_searches WHERE id = %s AND user_id = %s",
        (search_id, g.user_id),
    )
    cur.connection.commit()
    return "", 204