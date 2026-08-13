from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("preferences", __name__, url_prefix="/api/preferences")

FUNDING_FILTERS = {"both", "a", "b"}


@bp.get("")
@require_auth
def get_preferences():
    cur = get_cursor()
    cur.execute(
        """
        SELECT default_job_title, default_variants, default_posted_within_days,
               default_funding_filter, has_set_default_filters
        FROM users
        WHERE id = %s
        """,
        (g.user_id,),
    )
    return jsonify(cur.fetchone())


@bp.put("")
@require_auth
def update_preferences():
    body = request.get_json(silent=True) or {}

    # Variants count is no longer a user-adjustable filter — always 15.
    variants = 15

    funding_filter = body.get("funding_filter", "both")
    if funding_filter not in FUNDING_FILTERS:
        return jsonify({"error": "funding_filter must be 'both', 'a', or 'b'"}), 400

    posted_within_days = body.get("posted_within_days") or None
    if posted_within_days is not None:
        try:
            posted_within_days = int(posted_within_days)
        except (TypeError, ValueError):
            return jsonify({"error": "posted_within_days must be a number"}), 400

    cur = get_cursor()
    cur.execute(
        """
        UPDATE users
        SET default_job_title = %s,
            default_variants = %s,
            default_posted_within_days = %s,
            default_funding_filter = %s,
            has_set_default_filters = true
        WHERE id = %s
        RETURNING default_job_title, default_variants, default_posted_within_days,
                  default_funding_filter, has_set_default_filters
        """,
        (
            (body.get("job_title") or "").strip() or None,
            variants,
            posted_within_days,
            funding_filter,
            g.user_id,
        ),
    )
    updated = cur.fetchone()
    cur.connection.commit()

    return jsonify(updated)
