import json
import re

from flask import Blueprint, current_app, jsonify, request

from auth_utils import optional_auth
from db.connection import get_cursor
from title_variant_agent import get_title_variants as ask_variant_agent

bp = Blueprint("title_variants", __name__, url_prefix="/api/title-variants")

VARIANT_COUNT = 15


def normalize_title(title):
    return re.sub(r"\s+", " ", title.strip().lower())


def generate_variants(job_title):
    """Top 15 variants for job_title, straight from the VariantAgent (Claude).
    Independent of the `jobs` table -- this is the agent's own knowledge of
    real-world equivalent titles, not a match against postings already
    scraped. Only ever called on a job_title_variants cache miss. Raises on
    any failure; the route below turns that into a 502.
    """
    api_key = current_app.config.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not configured")

    data = ask_variant_agent(job_title, api_key=api_key)
    ranked = sorted(data["variants"], key=lambda row: row["rank"])
    titles = [row["title"] for row in ranked]

    if not titles:
        raise ValueError(f"VariantAgent returned no variants for {job_title!r}")

    return titles[:VARIANT_COUNT]


@bp.get("")
@optional_auth
def get_title_variants():
    job_title = (request.args.get("title") or "").strip()
    if not job_title:
        return jsonify({"error": "title query param is required"}), 400

    normalized = normalize_title(job_title)
    cur = get_cursor()

    # 1. Exact-title cache hit (shared across all users) -> serve straight
    #    from the DB, no agent call needed.
    cur.execute(
        "SELECT job_title, variants, generated_at FROM job_title_variants WHERE normalized_title = %s",
        (normalized,),
    )
    cached = cur.fetchone()
    if cached:
        return jsonify({**cached, "cached": True})

    # 2. Cache miss -> ask the VariantAgent for its own top 15 variants of
    #    this title (independent of what's in the `jobs` table), then write
    #    the result with a timestamp so nobody else has to pay for another
    #    Claude call for this exact title again.
    try:
        variants = generate_variants(job_title)
    except Exception as exc:  # noqa: BLE001 - surface any agent failure as a 502
        current_app.logger.exception("title-variants generation failed for %r", job_title)
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