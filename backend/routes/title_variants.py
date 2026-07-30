import json
import re

from flask import Blueprint, current_app, jsonify, request

from auth_utils import optional_auth
from db.connection import get_cursor

bp = Blueprint("title_variants", __name__, url_prefix="/api/title-variants")

VARIANT_COUNT = 15


def normalize_title(title):
    return re.sub(r"\s+", " ", title.strip().lower())


def find_closest_titles_in_db(cur, job_title, limit=VARIANT_COUNT):
    """Finds real job titles already in the `jobs` table that are the closest
    fuzzy match to job_title, using Postgres trigram similarity (pg_trgm) --
    the same extension/index schema.sql already sets up for title search.
    Excludes the exact title itself (case-insensitive): these are meant to
    be *variants* of what the user searched, not a repeat of it. One row
    per distinct title text, so a title posted at 50 companies only shows
    up once.
    """
    cur.execute(
        """
        WITH scored AS (
            SELECT DISTINCT ON (lower(title))
                   title,
                   similarity(title, %(title)s) AS score
            FROM jobs
            WHERE title %% %(title)s
              AND lower(title) <> lower(%(title)s)
            ORDER BY lower(title), score DESC
        )
        SELECT title
        FROM scored
        ORDER BY score DESC
        LIMIT %(limit)s
        """,
        {"title": job_title, "limit": limit},
    )
    return [row["title"] for row in cur.fetchall()]


@bp.get("")
@optional_auth
def get_title_variants():
    job_title = (request.args.get("title") or "").strip()
    if not job_title:
        return jsonify({"error": "title query param is required"}), 400

    normalized = normalize_title(job_title)
    cur = get_cursor()

    # 1. Exact-title cache hit (shared across all users) -> serve straight
    #    from the DB, no similarity query needed.
    cur.execute(
        "SELECT job_title, variants, generated_at FROM job_title_variants WHERE normalized_title = %s",
        (normalized,),
    )
    cached = cur.fetchone()
    if cached:
        return jsonify({**cached, "cached": True})

    # 2. Cache miss -> find the closest real titles already in the jobs
    #    table, then write the result with a timestamp so nobody else has
    #    to recompute it for this exact title again.
    try:
        variants = find_closest_titles_in_db(cur, job_title)
    except Exception as exc:  # noqa: BLE001 - surface any query failure as a 502
        current_app.logger.exception("title-variants similarity query failed")
        return jsonify({"error": f"Could not generate variants: {exc}"}), 502

    cur.execute(
        """
        INSERT INTO job_title_variants (job_title, normalized_title, variants)
        VALUES (%s, %s, %s)
        ON CONFLICT (normalized_title)
        DO UPDATE SET variants = EXCLUDED.variants, generated_at = now()
        RETURNING job_title, variants, generated_at
        """,
        (job_title, normalized, json.dumps(variants)),
    )
    saved = cur.fetchone()
    cur.connection.commit()

    return jsonify({**saved, "cached": False})

