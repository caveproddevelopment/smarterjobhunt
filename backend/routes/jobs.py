import re

from flask import Blueprint, g, jsonify, request

from auth_utils import optional_auth
from db.connection import get_cursor

bp = Blueprint("jobs", __name__, url_prefix="/api")

FUNDING_FILTER_MAP = {"a": "series_a", "b": "series_b"}  # 'both' applies no filter

# The backend's list of real Company Database categories (distinct from the
# 'both' filter value, which means "no restriction" rather than being a
# category itself). Kept in sync BY HAND with two other places, since Python
# and the frontend's JS can't share this literal directly:
#   - the CHECK (company_type IN (...)) constraints on companies.company_type
#     and saved_searches.company_type in db/schema.sql
#   - COMPANY_TYPES in frontend/src/lib/companyTypes.js
# Unknown values here are silently ignored (see the `if company_type in
# COMPANY_TYPES` checks below) rather than raising an error, so it's easy to
# forget this one when adding a database -- the symptom is the new filter
# quietly doing nothing instead of a visible failure.
COMPANY_TYPES = {"funded", "fortune500", "indianmajor", "midsize", "healthcare"}

# A job card needs at least a department OR a location to be worth showing.
# Scraped rows sometimes store an empty string ('') rather than a true SQL
# NULL for a missing field, so NULLIF(col, '') normalizes both cases to NULL
# before the IS NOT NULL check -- '' and NULL are treated identically here.
# Reused verbatim in three places (list_jobs, company_jobs, and
# company_type_counts) so the sidebar counts and both job-listing endpoints
# always agree on which jobs are "displayable".
HAS_DEPT_OR_LOCATION = "(NULLIF(j.department, '') IS NOT NULL OR NULLIF(j.location, '') IS NOT NULL)"


def _tokenize_title(title):
    """Split a search title into whitespace-separated terms for word-overlap
    scoring. e.g. "Senior Project Manager" -> ["Senior", "Project", "Manager"].
    """
    return [t for t in title.split() if t]


def _word_boundary_pattern(term):
    """Build a Postgres word-boundary regex (\\y...\\y) for a single term,
    escaping any regex metacharacters in the term itself first so terms like
    "C++" or "UX/UI" are matched literally rather than as regex syntax. \\y
    (not a bare substring) avoids short terms like "PM" false-positive
    matching inside an unrelated word.
    """
    return r"\y" + re.escape(term) + r"\y"


def _description_boost_expr(terms):
    """0-100 weighted word-overlap score of the search terms against a
    job's description (j.raw_text). Same per-word CASE-sum shape as
    _title_score_expr, just against a different column.

    Called multiple times by list_jobs -- each occurrence in the final SQL
    needs its own copy of the returned params spliced in at the matching
    position, since psycopg2 params are positional.

    Returns (sql_expr, params), or (None, []) when there are no terms (e.g.
    an empty/no-title search). Deliberately NOT a bare literal like "0" when
    unused directly in things like ORDER BY -- see the individual call
    sites below, which each substitute their own literal for the "nothing
    to score" case rather than reusing this return value directly as SQL
    text.

    Perf note: this is a regex scan of raw_text across every j.is_active
    row in scope. Fine at current scale (hundreds of jobs); if the jobs
    table grows into the tens of thousands, revisit with a tsvector + GIN
    index instead of a live regex scan -- same caution the ingestion
    agent's job_sink.py already flagged for this field back when it was
    still a MySQL FULLTEXT-index note.
    """
    if not terms:
        return None, []
    percent_per_term = 100.0 / len(terms)
    score_terms = []
    params = []
    for term in terms:
        score_terms.append(
            f"(CASE WHEN j.raw_text ~* %s THEN {percent_per_term} ELSE 0 END)"
        )
        params.append(_word_boundary_pattern(term))
    return "(" + " + ".join(score_terms) + ")", params


def _title_score_expr(terms):
    """0-100 weighted word-overlap score of the search terms against a
    job's title -- same per-word CASE-sum shape as _description_boost_expr,
    just against j.title instead of j.raw_text. This is the *raw*
    word-overlap score only; it doesn't know about exact phrase/variant
    hits -- see _effective_title_expr, which layers that on top.

    Returns (sql_expr, params), or (None, []) when there are no terms.
    """
    if not terms:
        return None, []
    percent_per_term = 100.0 / len(terms)
    score_terms = []
    params = []
    for term in terms:
        score_terms.append(
            f"(CASE WHEN j.title ~* %s THEN {percent_per_term} ELSE 0 END)"
        )
        params.append(_word_boundary_pattern(term))
    return "(" + " + ".join(score_terms) + ")", params


def _phrase_match_expr(candidates):
    """Boolean SQL expression: true if j.title ILIKE's any of the given
    exact phrases -- the typed title itself plus its up-to-15 cached
    variants, e.g. searching "PM" but a job titled "Senior Product
    Manager" hits the "Product Manager" variant. This is a substring
    check on the literal phrase, independent of the word-overlap scoring
    in _title_score_expr.

    Returns (sql_expr, params), or (None, []) when there are no candidates
    to check.
    """
    if not candidates:
        return None, []
    parts = []
    params = []
    for candidate in candidates:
        parts.append("j.title ILIKE %s")
        params.append(f"%{candidate}%")
    return "(" + " OR ".join(parts) + ")", params


def _effective_title_expr(phrase_expr, phrase_params, title_score_expr, title_score_params):
    """The title-side score used everywhere below: an exact ILIKE hit on
    the typed title OR any of its cached variants counts as a full 100 --
    a literal phrase match is a stronger signal than any partial
    word-overlap total could be. Without this boost, a job pulled in via a
    variant phrase that shares none of the *typed* words (e.g. typing
    "Technical Program Manager" but matching the cached variant "Product
    Owner") would still be scored only against the typed words, showing a
    low, disconnected percentage unrelated to why it actually matched.
    Falls back to the bag-of-words word-overlap score (_title_score_expr)
    when there's no phrase hit.

    Returns (sql_expr, params). Always returns a real numeric expression
    (COALESCEd to 0), never None, so every caller below can embed it
    directly without its own None-handling.
    """
    title_part = title_score_expr if title_score_expr is not None else "0"
    if phrase_expr is None:
        return f"COALESCE(({title_part}), 0)", list(title_score_params)
    return (
        f"(CASE WHEN {phrase_expr} THEN 100 ELSE COALESCE(({title_part}), 0) END)",
        [*phrase_params, *title_score_params],
    )


def _inclusion_gate_expr(effective_title_expr, effective_title_params, desc_score_expr, desc_score_params):
    """Whether a job qualifies for the search results at all: the
    (phrase-boosted) title score must reach 50, OR the description score
    must reach 50 on its own. Replaces the old "any single word matched"
    threshold (title score > 0) -- a job whose title only weakly overlaps
    the search (e.g. one matched word out of three, 33%) no longer
    qualifies via title alone; the description has to make up the
    difference instead, or the job is excluded entirely.

    effective_title_expr's params need splicing in once here (it appears
    once in the text); desc_score_expr's params likewise once.
    """
    desc_part = desc_score_expr if desc_score_expr is not None else "0"
    desc_part_params = list(desc_score_params) if desc_score_expr is not None else []
    expr = f"(({effective_title_expr}) >= 50 OR ({desc_part}) >= 50)"
    return expr, [*effective_title_params, *desc_part_params]


def _search_match_percent_expr(effective_title_expr, effective_title_params, desc_score_expr, desc_score_params):
    """The 0-100 "match %" shown on each job card: the (phrase-boosted)
    title score when it clears 50, otherwise the description word-overlap
    score. Deliberately NOT a blend of the two -- whichever one actually
    cleared the 50% bar is the one that qualified the job for inclusion
    (see _inclusion_gate_expr, the identical pair of checks), so the
    number on the card always matches the reason the job showed up.

    effective_title_expr appears TWICE in the text below (once in the WHEN
    condition, once in the THEN branch), so its params need to be spliced
    in twice to match; desc_score_expr appears once, in ELSE.
    """
    desc_part = desc_score_expr if desc_score_expr is not None else "0"
    desc_part_params = list(desc_score_params) if desc_score_expr is not None else []
    expr = (
        f"ROUND(CASE WHEN ({effective_title_expr}) >= 50 "
        f"THEN ({effective_title_expr}) ELSE ({desc_part}) END)::int"
    )
    return expr, [*effective_title_params, *effective_title_params, *desc_part_params]


def _top_tier_expr(effective_title_expr, effective_title_params, desc_score_expr, desc_score_params):
    """True only when EVERY typed word is present in both the title (or an
    exact phrase/variant hit) AND the description -- the "perfect match"
    tier that sorts above everything else, newest first (see the ORDER BY
    in list_jobs). Both sides are ROUNDed before comparing to 100: summing
    several equal fractional term scores (e.g. three terms at 100/3 each)
    can land a hair off 100 due to floating-point rounding, so an exact
    `= 100` check on the raw float could silently miss a job that actually
    matched every word.

    effective_title_expr's params need splicing in once here; desc_score_expr's
    likewise once.
    """
    desc_part = desc_score_expr if desc_score_expr is not None else "0"
    desc_part_params = list(desc_score_params) if desc_score_expr is not None else []
    expr = f"(ROUND(({effective_title_expr})) = 100 AND ROUND(({desc_part})) = 100)"
    return expr, [*effective_title_params, *desc_part_params]


@bp.get("/jobs")
@optional_auth
def list_jobs():
    title = request.args.get("title", "").strip()
    variant_titles = [v.strip() for v in request.args.getlist("variant_title") if v.strip()]
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()
    company_type = request.args.get("company_type", "both").strip().lower()
    company_id = request.args.get("company_id", "").strip()
    status_filter = request.args.get("status", "").strip().lower()
    remote_only = request.args.get("remote_only", "").strip().lower() in {"1", "true", "yes"}
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    where = []
    params = []

    terms = _tokenize_title(title) if title else []

    # Computed once, up front, so they're available for the WHERE-clause
    # gating below and again for the SELECT-list percent/tier columns.
    desc_score_expr, desc_score_params = _description_boost_expr(terms)
    title_score_expr, title_score_params = _title_score_expr(terms)

    # "Track Applications" (Applied / Rejected / All) is a history view of
    # what the user has marked, not a normal browse -- a job they applied
    # to may have gone inactive since, and they still want it to show up,
    # so is_active is skipped entirely whenever this mode is on.
    if status_filter not in {"applied", "rejected", "tracked"}:
        where.append("j.is_active = true")

    # Data-quality guard: a job scraped with NEITHER a department nor a
    # location is missing too much to render a useful card -- exclude it.
    # A job with only one of the two still has something to show, so this
    # only drops rows where both are missing (not either/or). Treats an
    # empty string the same as a true NULL (see HAS_DEPT_OR_LOCATION).
    where.append(HAS_DEPT_OR_LOCATION)

    # Title-driven search is active whenever either a typed title or at
    # least one variant pill is present -- same gate the old code used.
    # variant_titles is already pre-filtered to non-empty strings above,
    # so titled_search_active implies there's always at least one real
    # candidate phrase to check (title itself, or a variant).
    titled_search_active = bool(title or variant_titles)

    if titled_search_active:
        candidates = [c for c in [title, *variant_titles] if c]
        phrase_expr, phrase_params = _phrase_match_expr(candidates)
        effective_title_expr, effective_title_params = _effective_title_expr(
            phrase_expr, phrase_params, title_score_expr, title_score_params
        )

        gate_expr, gate_params = _inclusion_gate_expr(
            effective_title_expr, effective_title_params, desc_score_expr, desc_score_params
        )
        where.append(gate_expr)
        params.extend(gate_params)

        search_match_expr, search_match_params = _search_match_percent_expr(
            effective_title_expr, effective_title_params, desc_score_expr, desc_score_params
        )
        top_tier_expr, top_tier_params = _top_tier_expr(
            effective_title_expr, effective_title_params, desc_score_expr, desc_score_params
        )
    else:
        # Pure browse, no title/variant typed -- nothing to score against,
        # so no match % and no "perfect match" tier; sort falls straight
        # through to the AI match score (if any) then plain recency, same
        # as before this feature existed.
        search_match_expr, search_match_params = None, []
        top_tier_expr, top_tier_params = "false", []

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    if company_type in COMPANY_TYPES:
        where.append("c.company_type = %s")
        params.append(company_type)

    # "Remote" checkbox in the sidebar: word-boundary match (same \y
    # helper the title/description scoring above uses) against title,
    # location, and the full scraped description -- ANY of the three
    # mentioning "remote" qualifies, so e.g. a job titled without it but
    # whose location says "Remote (US)" still matches.
    if remote_only:
        remote_pattern = _word_boundary_pattern("remote")
        where.append("(j.title ~* %s OR j.location ~* %s OR j.raw_text ~* %s)")
        params.extend([remote_pattern, remote_pattern, remote_pattern])

    # "See them all" on a job card: scope to exactly one company by id
    # (never by name -- company names aren't guaranteed unique, id is).
    # The frontend sends no title/variant/posted_days/company_type filters
    # alongside this, so in practice it's the only clause besides is_active.
    if company_id:
        where.append("c.id = %s")
        params.append(int(company_id))

    # Scopes to the current user's application-tracking history instead of
    # the normal title-driven search. Checked against the fixed set above,
    # never interpolated from raw input, so the f-string below stays safe.
    # For a logged-out user g.user_id is None, the join below never matches
    # anything, s.status comes back NULL for every row, and these clauses
    # naturally filter down to zero results rather than erroring.
    if status_filter == "applied":
        where.append("s.status = 'applied'")
    elif status_filter == "rejected":
        where.append("s.status = 'rejected'")
    elif status_filter == "neither":
        # Unlike the other branches, "IS NULL" is true for every row once the
        # LEFT JOIN can't match anything (logged-out g.user_id is None) --
        # the opposite of what applied/rejected/tracked naturally fall back
        # to. Guard explicitly so a logged-out caller still gets zero rows,
        # matching the Track Applications section being hidden until login.
        where.append("s.status IS NULL" if g.user_id is not None else "false")
    elif status_filter == "tracked":
        where.append("s.status IS NOT NULL")

    where_clause = " AND ".join(where) if where else "true"

    count_query = f"""
        SELECT count(*)
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN user_job_status s ON s.job_id = j.id AND s.user_id = %s
        WHERE {where_clause}
    """
    cur = get_cursor()
    cur.execute(count_query, [g.user_id, *params])
    total_count = cur.fetchone()["count"]

    # NOTE: the inner SELECT is wrapped in a derived table ("results") on
    # purpose. Postgres only resolves a SELECT-list alias (is_perfect_match,
    # search_match_percent) as a bare top-level ORDER BY item -- e.g. plain
    # `is_perfect_match DESC` works fine. But the moment that alias sits
    # inside a larger expression, like the CASE statements below, Postgres
    # stops treating it as an alias and tries to resolve it as a real input
    # column on jobs/companies/job_matches/user_job_status instead, which
    # doesn't exist -> UndefinedColumn. Wrapping in a subquery makes
    # is_perfect_match/search_match_percent/match/date_posted genuine output
    # columns of "results", so the outer ORDER BY can reference them freely
    # inside CASE expressions. Purely a SQL-text restructure -- doesn't
    # change the params list or their order at all.
    query = f"""
        SELECT * FROM (
            SELECT
                j.id,
                j.title,
                j.department,
                j.location,
                j.date_posted,
                j.source_url,
                c.id AS company_id,
                c.name AS company,
                c.website AS company_website,
                c.funding_stage AS funding,
                c.company_type AS company_type,
                (
                    SELECT count(*) FROM jobs j2
                    WHERE j2.company_id = c.id AND j2.is_active AND j2.id != j.id
                ) AS other_jobs_at_company,
                m.match_percent AS match,
                {search_match_expr if search_match_expr is not None else 'NULL'} AS search_match_percent,
                {top_tier_expr} AS is_perfect_match,
                s.status,
                s.reason_rejected
            FROM jobs j
            JOIN companies c ON c.id = j.company_id
            LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
            LEFT JOIN user_job_status s ON s.job_id = j.id AND s.user_id = %s
            WHERE {where_clause}
        ) AS results
        ORDER BY
            match DESC NULLS LAST,
            is_perfect_match DESC,
            CASE WHEN is_perfect_match THEN date_posted END DESC NULLS LAST,
            CASE WHEN NOT is_perfect_match THEN search_match_percent END DESC NULLS LAST,
            date_posted DESC
        LIMIT %s OFFSET %s
    """
    # Order must match the placeholders left-to-right in the text above:
    # search_match_percent's params, then is_perfect_match's, then the two
    # join conditions, then the WHERE clause's own params (gate + the
    # simple filters appended after it), then LIMIT/OFFSET. Unchanged by
    # the subquery wrap above -- no new placeholders were introduced.
    full_params = [
        *search_match_params,
        *top_tier_params,
        g.user_id,
        g.user_id,
        *params,
        limit,
        offset,
    ]

    cur.execute(query, full_params)
    jobs = cur.fetchall()

    return jsonify({"jobs": jobs, "count": len(jobs), "total_count": total_count})


@bp.get("/jobs/variant-counts")
@optional_auth
def variant_counts():
    """How many active jobs match each of the given title variants, one at a
    time -- e.g. {"Product Owner": 4, "Senior Product Manager": 0, ...}.
    Powers the clickable "Also matching" pills: a variant with a count of 0
    isn't worth letting someone click into. Each variant is counted on its
    own (never OR'd with the others or with the main title), since a click
    on a pill should show ONLY that variant's jobs. posted_days/funding are
    accepted so the counts match whatever's currently applied everywhere
    else on the page.
    """
    variant_titles = [v.strip() for v in request.args.getlist("variant_title") if v.strip()]
    posted_days = request.args.get("posted_days", "").strip()
    funding = request.args.get("funding", "both").strip().lower()
    company_type = request.args.get("company_type", "both").strip().lower()

    if not variant_titles:
        return jsonify({"counts": {}})

    # Note the doubled %% -- these are literal wildcard characters sitting
    # in the query text itself (not a bound parameter), and psycopg2 treats
    # a bare % in the query as the start of a %s/%(name)s placeholder once
    # any parameters are being passed, so it must be escaped.
    where = ["j.is_active = true", "j.title ILIKE '%%' || v.title || '%%'"]
    params = []

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    if company_type in COMPANY_TYPES:
        where.append("c.company_type = %s")
        params.append(company_type)

    where_clause = " AND ".join(where)

    # A correlated subquery per unnested variant keeps each count
    # independent (no cross-variant double counting) while still costing a
    # single round trip to the DB for all 15 variants.
    query = f"""
        SELECT
            v.title AS variant_title,
            (
                SELECT count(*)
                FROM jobs j
                JOIN companies c ON c.id = j.company_id
                WHERE {where_clause}
            ) AS job_count
        FROM unnest(%s::text[]) WITH ORDINALITY AS v(title, ord)
        ORDER BY v.ord
    """
    full_params = [*params, variant_titles]

    cur = get_cursor()
    cur.execute(query, full_params)
    rows = cur.fetchall()

    counts = {row["variant_title"]: row["job_count"] for row in rows}
    return jsonify({"counts": counts})


@bp.get("/jobs/company-type-counts")
@optional_auth
def company_type_counts():
    """Total active jobs in each company database, e.g.
    {"funded": 1025, "fortune500": 1500, "both": 2525}. Powers the counts
    shown next to "Funded Startups" / "Fortune 500" / "Both" in the
    sidebar. Not scoped to title, posted_days, or any other search filter --
    just the total size of each database -- but IS scoped by the same
    department/location displayability guard as list_jobs and company_jobs
    (see HAS_DEPT_OR_LOCATION), so these counts stay in sync with what a
    user would actually see if they browsed that database.
    """
    cur = get_cursor()
    cur.execute(
        f"""
        SELECT c.company_type, count(*) AS job_count
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.is_active = true
          AND {HAS_DEPT_OR_LOCATION}
        GROUP BY c.company_type
        """
    )
    rows = cur.fetchall()

    # Keep the response keyed by every real company database, plus "all"
    # for the unfiltered view. "both" is retained as a backwards-compatible
    # alias for clients that still expect the old two-database response.
    counts = {company_type: 0 for company_type in COMPANY_TYPES}
    for row in rows:
        if row["company_type"] in counts:
            counts[row["company_type"]] = row["job_count"]

    counts["all"] = sum(counts.values())
    counts["both"] = counts["all"]

    return jsonify({"counts": counts})


@bp.get("/companies/<int:company_id>/jobs")
@optional_auth
def company_jobs(company_id):
    cur = get_cursor()
    cur.execute(
        f"""
        SELECT
            j.id, j.title, j.department, j.location, j.date_posted,
            m.match_percent AS match
        FROM jobs j
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        WHERE j.company_id = %s AND j.is_active = true
          AND {HAS_DEPT_OR_LOCATION}
        ORDER BY j.date_posted DESC
        """,
        (g.user_id, company_id),
    )
    return jsonify({"jobs": cur.fetchall()})