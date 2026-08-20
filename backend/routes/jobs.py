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
COMPANY_TYPES = {"funded", "fortune500"}


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
    """Same per-word scoring shape as the title word-overlap gate below, but
    against j.raw_text (the scraped job description) instead of j.title.

    Called multiple times by list_jobs, each with its own copy of the
    returned params spliced into full_params at the matching position:
      1. In the WHERE clause, OR'd alongside the title/variant checks, as a
         fallback -- if a job's title doesn't match the search at all, it
         can still be included when the typed title's words show up in its
         description at 100% weighted coverage.
      2. In ORDER BY, to rank jobs with higher description-word overlap
         above otherwise-equal jobs. This half never excludes anything by
         itself -- a job already included via a title match keeps its slot
         even if its description score is 0, it just sorts lower.
      3. Inside _search_match_percent_expr, blended with the title score
         into the search_match_percent column shown on each job card.

    Deliberately scores against the typed `title`'s individual words only,
    not the 15 title variants -- keeps this easy to reason about. Could be
    extended to also check variant phrases in raw_text later if useful.

    Returns (sql_expr, params). sql_expr is a numeric 0-100 CASE-sum, or
    None (no params, nothing to score) when there are no terms -- e.g. an
    empty/no-title search. Deliberately NOT a bare literal like "0": any
    plain constant dropped straight into an ORDER BY clause is treated by
    Postgres as an attempted positional column reference (SQL92 rule) and
    errors unless it's a valid integer position -- confirmed against a
    live Postgres 16 instance, where `ORDER BY 0` fails as "position 0 is
    not in select list" and even `ORDER BY 0.0` fails as "non-integer
    constant in ORDER BY". So callers must substitute a real expression of
    their own for the "nothing to score" case (see order_by_boost in
    list_jobs, which casts a literal via `0::numeric` so it's no longer a
    bare constant) rather than reusing this return value directly as SQL
    text.
    Note sql_expr, when not None, is plain SQL text reused verbatim at two
    call sites in the query below -- each occurrence needs its own copy of
    params spliced in at the matching position, since psycopg2 params are
    positional.

    Perf note: this is a regex scan of raw_text, and as of the WHERE-clause
    fallback above it can now run across every j.is_active row in scope
    (not just ones that already passed a title match), once per ORDER BY
    evaluation. Fine at current scale (hundreds of jobs); if the jobs table
    grows into the tens of thousands, revisit with a tsvector + GIN index
    instead of a live regex scan -- same caution the ingestion agent's
    job_sink.py already flagged for this field back when it was still a
    MySQL FULLTEXT-index note.
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
    just against j.title instead of j.raw_text. Kept as its own standalone
    function (rather than reusing the inline score_terms block in the
    title_matches WHERE-clause builder below) so building this display-only
    percentage can never perturb that block's existing filtering behavior.

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


# Weights for the job-card "search match %": how much of the combined score
# comes from the title vs. the description. Title counts for more since an
# exact/near title match is a stronger signal than the search words merely
# appearing somewhere in the description.
TITLE_MATCH_WEIGHT = 0.7
DESCRIPTION_MATCH_WEIGHT = 0.3


def _search_match_percent_expr(terms):
    """Combined 0-100 "how well does this job match what was typed" score,
    blending the title word-overlap score and the description word-overlap
    score with the weights above. This is the number shown on each job card
    (via MatchRing) -- distinct from job_matches.match_percent, which is a
    separate per-user AI-computed score against a resume, not against the
    currently typed search title.

    Returns (sql_expr, params), or (None, []) when there's no title typed at
    all (nothing to score against, so the card shows no ring).
    """
    title_expr, title_params = _title_score_expr(terms)
    desc_expr, desc_params = _description_boost_expr(terms)
    if title_expr is None:
        return None, []
    combined = (
        f"ROUND(({TITLE_MATCH_WEIGHT} * {title_expr}) "
        f"+ ({DESCRIPTION_MATCH_WEIGHT} * {desc_expr}))::int"
    )
    return combined, [*title_params, *desc_params]


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
    limit = min(int(request.args.get("limit", 50)), 500)
    offset = int(request.args.get("offset", 0))

    where = []
    params = []

    terms = _tokenize_title(title) if title else []

    # Computed once, up front, so it's available both for the WHERE-clause
    # fallback below (title didn't match -> try the description instead)
    # and again later for ORDER BY. See _description_boost_expr's docstring
    # for why the same (expr, params) pair gets spliced into the final SQL
    # at two separate positions.
    desc_score_expr, desc_score_params = _description_boost_expr(terms)

    # Same terms, used for the job-card match-percent column in SELECT
    # below (title + description blended). Computed up front, next to
    # desc_score_expr, for the same reason: its params need to land in
    # full_params in the exact position this expression's %s placeholders
    # end up appearing in the final query text (see full_params below).
    search_match_expr, search_match_params = _search_match_percent_expr(terms)

    # "Track Applications" (Applied / Rejected / All) is a history view of
    # what the user has marked, not a normal browse -- a job they applied
    # to may have gone inactive since, and they still want it to show up,
    # so is_active is skipped entirely whenever this mode is on.
    if status_filter not in {"applied", "rejected", "tracked"}:
        where.append("j.is_active = true")

    # Title + its variants are OR'd together as one group (any of them can
    # match), then AND'd with the other filters below. The frontend always
    # sends up to the full 15 cached/generated variants for the title (the
    # variants count is fixed, not user-selectable).
    #
    # A job that matches none of those exact phrases still gets included if
    # at least half of the *typed* title's individual words appear in it
    # (each word weighted 100/word-count, summed, included if the total is
    # >=50%). e.g. searching "Senior Project Manager" against a job titled
    # "Project Manager" scores 66% and is shown even though neither the
    # exact title nor any of the 15 variants matched it as a phrase. This
    # >=50 threshold means a 2-word search needs only one word present to
    # qualify (50% >= 50%). This is folded into
    # the same OR group as the exact/variant checks above -- "match A OR
    # match B" gives the identical result as "if A: show, elif B: show".
    # Word terms are matched on a word boundary rather than a bare
    # substring, so a short word like "PM" can't match inside an unrelated
    # word the way ILIKE '%PM%' would.
    #
    # Threshold is '>= 50' (not a strict '>'), so with exactly 2 typed
    # terms -- each worth exactly 50% -- a single matching word out of two
    # is enough to clear this check on its own. Kept consistent with the
    # description fallback just below, which uses the same >=50 threshold.
    if title or variant_titles:
        title_matches = []
        for candidate in [title, *variant_titles]:
            if candidate:
                title_matches.append("j.title ILIKE %s")
                params.append(f"%{candidate}%")

        if len(terms) > 1:
            percent_per_term = 100.0 / len(terms)
            score_terms = []
            for term in terms:
                score_terms.append(
                    f"(CASE WHEN j.title ~* %s THEN {percent_per_term} ELSE 0 END)"
                )
                params.append(_word_boundary_pattern(term))
            score_expr = " + ".join(score_terms)
            title_matches.append(f"(({score_expr}) >= 50)")

        # Fallback: only matters for jobs that missed every check above. If
        # the typed title's words turn up in the job's DESCRIPTION at a
        # complete coverage of 100%, include it too. OR'd into the same
        # group as the title checks, so a job that already matched on title
        # is completely unaffected -- this can only ever add jobs, never
        # remove or reorder them within this clause.
        if desc_score_expr:
            title_matches.append(f"(({desc_score_expr}) >= 100)")
            params.extend(desc_score_params)

        where.append("(" + " OR ".join(title_matches) + ")")

    if posted_days:
        where.append("j.date_posted >= CURRENT_DATE - %s::interval")
        params.append(f"{int(posted_days)} days")

    if funding in FUNDING_FILTER_MAP:
        where.append("c.funding_stage = %s")
        params.append(FUNDING_FILTER_MAP[funding])

    if company_type in COMPANY_TYPES:
        where.append("c.company_type = %s")
        params.append(company_type)

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
    elif status_filter == "tracked":
        where.append("s.status IS NOT NULL")

    where_clause = " AND ".join(where) if where else "true"

    # ORDER BY needs a real SQL expression on every request, including
    # empty/no-title searches where desc_score_expr is None. This can't be
    # a bare numeric literal of ANY kind -- Postgres's SQL92 ORDER BY rule
    # treats every plain constant (not just integers) as an attempted
    # positional column reference, and errors if it isn't a valid integer
    # position: `ORDER BY 0` -> "position 0 is not in select list", and
    # `ORDER BY 0.0` -> "non-integer constant in ORDER BY" (confirmed
    # against a live Postgres 16 instance). Casting it (`0::numeric`) makes
    # it a real expression rather than a bare constant, so it's never
    # special-cased, and it sorts as an inert placeholder same as any other
    # tie-breaker column would. No params needed for this literal either
    # way.
    order_by_boost = desc_score_expr if desc_score_expr is not None else "0::numeric"

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

    query = f"""
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
            s.status,
            s.reason_rejected
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        LEFT JOIN user_job_status s ON s.job_id = j.id AND s.user_id = %s
        WHERE {where_clause}
        ORDER BY m.match_percent DESC NULLS LAST, {order_by_boost} DESC, j.date_posted DESC
        LIMIT %s OFFSET %s
    """
    full_params = [
        *search_match_params,
        g.user_id,
        g.user_id,
        *params,
        *desc_score_params,
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
    sidebar. Deliberately unfiltered -- not scoped to title, posted_days,
    or any other search filter, just the total size of each database.
    """
    cur = get_cursor()
    cur.execute(
        """
        SELECT c.company_type, count(*) AS job_count
        FROM jobs j
        JOIN companies c ON c.id = j.company_id
        WHERE j.is_active = true
        GROUP BY c.company_type
        """
    )
    rows = cur.fetchall()

    counts = {"funded": 0, "fortune500": 0}
    for row in rows:
        if row["company_type"] in counts:
            counts[row["company_type"]] = row["job_count"]
    counts["both"] = counts["funded"] + counts["fortune500"]

    return jsonify({"counts": counts})


@bp.get("/companies/<int:company_id>/jobs")
@optional_auth
def company_jobs(company_id):
    cur = get_cursor()
    cur.execute(
        """
        SELECT
            j.id, j.title, j.department, j.location, j.date_posted,
            m.match_percent AS match
        FROM jobs j
        LEFT JOIN job_matches m ON m.job_id = j.id AND m.user_id = %s
        WHERE j.company_id = %s AND j.is_active = true
        ORDER BY j.date_posted DESC
        """,
        (g.user_id, company_id),
    )
    return jsonify({"jobs": cur.fetchall()})