from flask import Blueprint, jsonify, request

from auth_utils import require_admin_key
from db.connection import get_cursor

bp = Blueprint("staging", __name__, url_prefix="/api/admin/staging")

STAGING_FIELDS = """
    id, company_id, title, department, location, date_posted, source_url,
    raw_text, scraped_at, batch_id, review_status, reject_reason, promoted_at
"""


@bp.get("/batches")
@require_admin_key
def list_batches():
    """One row per scrape run with a status breakdown, most recent first --
    the entry point for review: see at a glance which batches still have
    'pending' rows worth looking at vs. ones that are fully approved,
    rejected, or already promoted."""
    cur = get_cursor()
    cur.execute(
        """
        SELECT
            batch_id,
            MIN(scraped_at) AS scraped_at,
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE review_status = 'pending')  AS pending,
            COUNT(*) FILTER (WHERE review_status = 'approved' AND promoted_at IS NULL)
                AS approved_unpromoted,
            COUNT(*) FILTER (WHERE review_status = 'rejected') AS rejected,
            COUNT(*) FILTER (WHERE promoted_at IS NOT NULL)    AS promoted
        FROM jobs_staging
        GROUP BY batch_id
        ORDER BY MIN(scraped_at) DESC
        """
    )
    return jsonify(cur.fetchall())


@bp.get("")
@require_admin_key
def list_staged():
    """List staged rows, optionally filtered to one batch. Defaults to
    review_status='pending' since that's what manual review actually needs
    day to day; pass review_status=all to see everything in a batch."""
    batch_id = request.args.get("batch_id")
    review_status = request.args.get("review_status", "pending")
    limit = min(int(request.args.get("limit", 100)), 500)
    offset = int(request.args.get("offset", 0))

    conditions = []
    params = []
    if review_status != "all":
        conditions.append("review_status = %s")
        params.append(review_status)
    if batch_id:
        conditions.append("batch_id = %s")
        params.append(batch_id)
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    cur = get_cursor()
    cur.execute(
        f"""
        SELECT {STAGING_FIELDS}
        FROM jobs_staging
        {where_clause}
        ORDER BY scraped_at DESC
        LIMIT %s OFFSET %s
        """,
        (*params, limit, offset),
    )
    return jsonify(cur.fetchall())


@bp.post("/<int:staging_id>/review")
@require_admin_key
def review_one(staging_id):
    """Manually approve or reject one staged row -- what a review UI (or a
    one-off curl call) hits for anything the auto-clean pass left
    'pending', or to override an auto-decision you disagree with."""
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    reason = body.get("reason")

    if status not in ("approved", "rejected"):
        return jsonify({"error": "status must be 'approved' or 'rejected'"}), 400

    cur = get_cursor()
    cur.execute(
        f"""
        UPDATE jobs_staging
        SET review_status = %s, reject_reason = %s
        WHERE id = %s
        RETURNING {STAGING_FIELDS}
        """,
        (status, reason if status == "rejected" else None, staging_id),
    )
    row = cur.fetchone()
    if row is None:
        cur.connection.rollback()
        return jsonify({"error": "Staged job not found"}), 404
    cur.connection.commit()
    return jsonify(row)


@bp.post("/clean")
@require_admin_key
def auto_clean():
    """Rule-based first pass over one batch's 'pending' rows: rejects
    obvious junk, approves rows with nothing wrong and enough content to
    trust, and leaves anything genuinely ambiguous as 'pending' for a
    human to decide on. Safe to re-run -- only ever touches rows still
    'pending', so re-running after a manual review pass won't undo
    anyone's decisions.

    These rules are a starting point, not gospel -- tune the thresholds
    and patterns below once you see what your scraper actually produces.
    """
    body = request.get_json(silent=True) or {}
    batch_id = body.get("batch_id")
    if not batch_id:
        return jsonify({"error": "batch_id is required"}), 400

    cur = get_cursor()

    # 1. Missing or malformed title -- can't be a real posting without one.
    cur.execute(
        """
        UPDATE jobs_staging
        SET review_status = 'rejected', reject_reason = 'missing or malformed title'
        WHERE batch_id = %s AND review_status = 'pending'
          AND (title IS NULL OR btrim(title) = ''
               OR char_length(btrim(title)) < 3 OR char_length(title) > 200)
        """,
        (batch_id,),
    )

    # 2. Obvious placeholder/nav-menu junk titles.
    cur.execute(
        r"""
        UPDATE jobs_staging
        SET review_status = 'rejected', reject_reason = 'junk/placeholder title'
        WHERE batch_id = %s AND review_status = 'pending'
          AND title ~* '^(apply now|careers?|jobs?|home|menu|navigation|n/?a|null|undefined|lorem ipsum|test)$'
        """,
        (batch_id,),
    )

    # 3. No source_url AND no raw_text -- nothing to verify or dedupe
    #    against, almost certainly a scrape failure rather than a real job.
    cur.execute(
        """
        UPDATE jobs_staging
        SET review_status = 'rejected',
            reject_reason = 'no source_url and no raw_text -- likely scrape failure'
        WHERE batch_id = %s AND review_status = 'pending'
          AND (source_url IS NULL OR btrim(source_url) = '')
          AND (raw_text IS NULL OR char_length(btrim(raw_text)) = 0)
        """,
        (batch_id,),
    )

    # 4. Exact duplicate within this batch (same company + source_url) --
    #    keep the earliest row, reject the rest.
    cur.execute(
        """
        UPDATE jobs_staging s
        SET review_status = 'rejected', reject_reason = 'duplicate of another row in this batch'
        WHERE s.batch_id = %s AND s.review_status = 'pending' AND s.source_url IS NOT NULL
          AND s.id > (
              SELECT MIN(s2.id) FROM jobs_staging s2
              WHERE s2.batch_id = s.batch_id AND s2.company_id = s.company_id
                AND s2.source_url = s.source_url
          )
        """,
        (batch_id,),
    )

    # 5. Everything still pending with a title, a source_url, and
    #    substantial raw_text has nothing obviously wrong -- auto-approve.
    #    Anything short of that (e.g. a title + source_url but thin or
    #    missing raw_text) stays 'pending' for manual review.
    cur.execute(
        """
        UPDATE jobs_staging
        SET review_status = 'approved'
        WHERE batch_id = %s AND review_status = 'pending'
          AND source_url IS NOT NULL AND btrim(source_url) <> ''
          AND raw_text IS NOT NULL AND char_length(btrim(raw_text)) >= 100
        """,
        (batch_id,),
    )

    cur.connection.commit()

    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE review_status = 'approved') AS approved,
            COUNT(*) FILTER (WHERE review_status = 'rejected') AS rejected,
            COUNT(*) FILTER (WHERE review_status = 'pending')  AS pending
        FROM jobs_staging WHERE batch_id = %s
        """,
        (batch_id,),
    )
    return jsonify(cur.fetchone())


@bp.post("/promote")
@require_admin_key
def promote():
    """Push every 'approved', not-yet-promoted row in a batch into the
    real jobs table, reusing the exact same (company_id, source_url)
    dedup index jobs already has -- so re-promoting an already-promoted
    batch, or a job that reappears in a later scrape, just updates the
    existing row instead of duplicating it. Staged rows are marked
    promoted_at rather than deleted, so the raw scrape history sticks
    around for debugging.
    """
    body = request.get_json(silent=True) or {}
    batch_id = body.get("batch_id")
    if not batch_id:
        return jsonify({"error": "batch_id is required"}), 400

    cur = get_cursor()
    cur.execute(
        """
        INSERT INTO jobs (company_id, title, department, location, date_posted, source_url, raw_text)
        SELECT company_id, title, department, location, date_posted, source_url, raw_text
        FROM jobs_staging
        WHERE batch_id = %s AND review_status = 'approved' AND promoted_at IS NULL
        ON CONFLICT (company_id, source_url) WHERE source_url IS NOT NULL DO UPDATE
        SET title = EXCLUDED.title, department = EXCLUDED.department,
            location = EXCLUDED.location, date_posted = EXCLUDED.date_posted,
            raw_text = EXCLUDED.raw_text, scraped_at = now(), is_active = true
        """,
        (batch_id,),
    )

    cur.execute(
        """
        UPDATE jobs_staging
        SET promoted_at = now()
        WHERE batch_id = %s AND review_status = 'approved' AND promoted_at IS NULL
        """,
        (batch_id,),
    )
    promoted_count = cur.rowcount
    cur.connection.commit()

    return jsonify({"batch_id": batch_id, "promoted": promoted_count})
