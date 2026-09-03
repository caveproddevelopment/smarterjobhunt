import psycopg2
from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("saved_searches", __name__, url_prefix="/api/saved-searches")

VALID_VIEW_TYPES = {"search", "variant", "company", "status"}
VALID_STATUS_FILTERS = {"applied", "rejected", "neither"}

# The five real Company Database categories a bookmark's company_type can be
# built from. Kept in sync BY HAND with COMPANY_TYPES in routes/jobs.py (see
# the warning comment there) -- this is the third by-hand copy referenced by
# that comment, alongside frontend/src/lib/companyTypes.js.
VALID_COMPANY_TYPES = {"funded", "fortune500", "indianmajor", "midsize", "healthcare"}


def _normalize_company_types(raw):
    """Turn whatever shape the frontend sent for company_types into a
    sorted, de-duplicated list of valid tokens.

    Accepts a JSON array (the documented shape) and, just in case, an
    already-comma-joined string -- either way the result is canonicalized
    (sorted + deduped) so the same set of selections always produces the
    same stored string regardless of the order they were checked in, which
    is what the uq_saved_searches_view unique index relies on to catch
    real duplicates.

    Raises ValueError(list_of_bad_tokens) if anything isn't one of the five
    real categories.
    """
    if isinstance(raw, list):
        candidates = raw
    elif isinstance(raw, str):
        candidates = raw.split(",")
    elif raw:
        candidates = [raw]
    else:
        candidates = []

    tokens = sorted({str(ct).strip().lower() for ct in candidates if str(ct).strip()})
    invalid = [ct for ct in tokens if ct not in VALID_COMPANY_TYPES]
    if invalid:
        raise ValueError(invalid)
    return tokens


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
            ss.remote_only, ss.created_at
        FROM saved_searches ss
        LEFT JOIN companies c ON c.id = ss.company_id
        WHERE ss.user_id = %s
        ORDER BY ss.created_at DESC
        """,
        (g.user_id,),
    )
    searches = cur.fetchall()
    # Convert comma-separated company_type back to array for API response.
    # 'all' means "no restriction" (the default/empty case), not a real
    # category, so it maps to an empty list rather than ["all"].
    for search in searches:
        if search.get("company_type") and search["company_type"] != "all":
            search["company_types"] = [ct.strip() for ct in search["company_type"].split(",") if ct.strip()]
        else:
            search["company_types"] = []
    return jsonify({"saved_searches": searches})


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

    # Handle company_types as an array (one or many boxes checked) -- convert
    # to a canonical comma-separated string for storage. Empty/unset means
    # "no restriction", which is what 'all' represents on this column --
    # NOT 'funded' (that was the old default, which mislabeled 'company' and
    # 'status' bookmarks, which never set company_types at all, as if the
    # user had filtered to Funded Startups).
    try:
        company_types = _normalize_company_types(body.get("company_types", []))
    except ValueError as e:
        return jsonify({"error": f"invalid company type(s): {', '.join(e.args[0])}"}), 400
    company_types_str = ",".join(company_types) if company_types else "all"

    cur = get_cursor()
    try:
        cur.execute(
            """
            INSERT INTO saved_searches
                (user_id, name, view_type, job_title, variant_title, variants,
                 posted_within_days, company_type, funding_filter, status_filter,
                 company_id, remote_only)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, view_type, job_title, variant_title,
                      posted_within_days, company_type, funding_filter,
                      status_filter, company_id, remote_only, created_at
            """,
            (
                g.user_id,
                name,
                view_type,
                body.get("job_title"),
                body.get("variant_title"),
                15,  # variants count is no longer user-adjustable — always 15
                body.get("posted_within_days"),
                company_types_str,
                body.get("funding_filter", "both"),
                status_filter,
                body.get("company_id"),
                bool(body.get("remote_only")),
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

    # Convert company_type string back to array for API response (see the
    # same 'all' handling as list_saved_searches above).
    if saved.get("company_type") and saved["company_type"] != "all":
        saved["company_types"] = [ct.strip() for ct in saved["company_type"].split(",") if ct.strip()]
    else:
        saved["company_types"] = []

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