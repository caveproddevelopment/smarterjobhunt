from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("preferences", __name__, url_prefix="/api/preferences")

@bp.get("")
@require_auth
def get_preferences():
    cur = get_cursor()
    cur.execute(
        """
        SELECT default_job_title, default_variants, default_posted_within_days,
               has_set_default_filters
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
            has_set_default_filters = true
        WHERE id = %s
        RETURNING default_job_title, default_variants, default_posted_within_days,
                  has_set_default_filters
        """,
        (
            (body.get("job_title") or "").strip() or None,
            variants,
            posted_within_days,
            g.user_id,
        ),
    )
    updated = cur.fetchone()
    cur.connection.commit()

    return jsonify(updated)
