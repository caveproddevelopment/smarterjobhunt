from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("job_status", __name__, url_prefix="/api/job-status")

VALID_STATUSES = {"applied", "rejected"}


@bp.put("/<int:job_id>")
@require_auth
def set_status(job_id):
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    reason_rejected = body.get("reason_rejected")

    if status not in VALID_STATUSES:
        return jsonify({"error": f"status must be one of {sorted(VALID_STATUSES)}"}), 400

    cur = get_cursor()
    cur.execute(
        """
        INSERT INTO user_job_status (user_id, job_id, status, reason_rejected, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (user_id, job_id)
        DO UPDATE SET status = EXCLUDED.status,
                      reason_rejected = EXCLUDED.reason_rejected,
                      updated_at = now()
        RETURNING job_id, status, reason_rejected, updated_at
        """,
        (g.user_id, job_id, status, reason_rejected),
    )
    result = cur.fetchone()
    cur.connection.commit()
    return jsonify(result)


@bp.delete("/<int:job_id>")
@require_auth
def clear_status(job_id):
    cur = get_cursor()
    cur.execute(
        "DELETE FROM user_job_status WHERE user_id = %s AND job_id = %s",
        (g.user_id, job_id),
    )
    cur.connection.commit()
    return "", 204
