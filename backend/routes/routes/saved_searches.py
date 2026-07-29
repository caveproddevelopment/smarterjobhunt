import psycopg2
from flask import Blueprint, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("saved_searches", __name__, url_prefix="/api/saved-searches")


@bp.get("")
@require_auth
def list_saved_searches():
    cur = get_cursor()
    cur.execute(
        """
        SELECT id, name, job_title, variants, posted_within_days, funding_filter, created_at
        FROM saved_searches
        WHERE user_id = %s
        ORDER BY created_at DESC
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

    cur = get_cursor()
    try:
        cur.execute(
            """
            INSERT INTO saved_searches
                (user_id, name, job_title, variants, posted_within_days, funding_filter)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, name, job_title, variants, posted_within_days, funding_filter, created_at
            """,
            (
                g.user_id,
                name,
                body.get("job_title"),
                body.get("variants", 10),
                body.get("posted_within_days"),
                body.get("funding_filter", "both"),
            ),
        )
        saved = cur.fetchone()
        cur.connection.commit()
    except psycopg2.errors.UniqueViolation:
        cur.connection.rollback()
        return jsonify({"error": "You already have a saved search with that name"}), 409

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
