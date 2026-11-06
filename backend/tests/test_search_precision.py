"""Which jobs a title search includes (backend/routes/jobs.py
_inclusion_gate_expr): the title must contain the searched title, one of its
variants, or every searched word; or the description must contain the searched
title or a variant as a whole phrase. One matching word is no longer enough.
Same throwaway-database setup as test_country_billing.py (needs SJH_TEST_DATABASE_URL)."""
import uuid

from tests.test_country_billing import US_IP, _register, db_url, env  # noqa: F401  (fixtures)

JOBS = [
    # (title, description, should match "Program Manager" with variant "Delivery Manager")
    ("Program Manager", "Lead cross-team programs.", True),                       # title phrase
    ("Senior Technical Program Manager", "Own the roadmap.", True),               # title phrase inside
    ("Manager, Clinical Program", "Oversee clinic operations.", True),            # all words, other order
    ("Senior Delivery Manager", "Ship releases on time.", True),                  # title variant
    ("Account Manager", "Work closely with the program manager on renewals.", True),  # description phrase
    ("Business Analyst", "Partner with our Delivery Manager each sprint.", True),     # description variant
    ("Store Manager", "Run the loyalty program and manage staff.", False),        # one title word + loose words
    ("Program Coordinator", "Coordinate the program calendar.", False),           # one title word only
    ("Nurse Practitioner", "Join our program; report to the clinic manager.", False),  # both words, not as phrase
    ("Software Engineer", "Write programs in Python.", False),                    # nothing
]


def _seed(env):
    db = env["db"]
    db.execute("INSERT INTO companies (name, company_type) VALUES (%s, 'funded') RETURNING id",
               (f"Acme {uuid.uuid4().hex[:6]}",))
    cid = db.fetchone()[0]
    ids = {}
    for title, desc, _ in JOBS:
        db.execute(
            "INSERT INTO jobs (company_id, title, raw_text, source_url, date_posted) "
            "VALUES (%s, %s, %s, %s, CURRENT_DATE) RETURNING id",
            (cid, title, desc, f"https://acme.test/{uuid.uuid4().hex}"))
        ids[title] = db.fetchone()[0]
    return ids


def _search(env, headers, **q):
    resp = env["client"].get("/api/jobs", query_string=q, headers=headers)
    assert resp.status_code == 200, resp.get_json()
    return resp.get_json()


def test_only_full_title_or_description_phrase_matches(env):
    ids = _seed(env)
    user_id, h = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    data = _search(env, h, title="Program Manager", variant_title="Delivery Manager", limit=50)
    got = {j["id"]: j for j in data["jobs"]}
    for title, _, expected in JOBS:
        assert (ids[title] in got) == expected, f"{title!r} should {'' if expected else 'not '}match"
    # count matches the list
    mine = [j for j in data["jobs"] if j["id"] in ids.values()]
    assert len(mine) == sum(1 for *_, e in JOBS if e)


def test_match_percent_follows_why_the_job_matched(env):
    ids = _seed(env)
    user_id, h = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    got = {j["id"]: j for j in _search(env, h, title="Program Manager", limit=50)["jobs"]}
    assert got[ids["Program Manager"]]["search_match_percent"] == 100
    assert got[ids["Manager, Clinical Program"]]["search_match_percent"] == 100
    # in via the description: shows the description's score, not the title's partial 50
    assert got[ids["Account Manager"]]["search_match_percent"] == 100


def test_single_word_search_still_works(env):
    ids = _seed(env)
    user_id, h = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    got = {j["id"] for j in _search(env, h, title="Engineer", limit=50)["jobs"]}
    assert ids["Software Engineer"] in got and ids["Store Manager"] not in got


def test_regex_characters_in_titles_are_literal(env):
    _seed(env)
    user_id, h = _register(env["client"], US_IP)
    env["db"].execute("UPDATE users SET plan = 'pro' WHERE id = %s", (user_id,))
    # would be an invalid / greedy regex if not escaped
    for title in ("C++ Developer", "UX/UI (Senior)", "Manager.*"):
        _search(env, h, title=title, variant_title="Program Manager+", limit=5)
