"""Sign-up campaign tracking: utm_source / utm_campaign / utm_content sent by the
frontend (first tagged link the person arrived through) land on the new user row.
Same throwaway-database setup as test_country_billing.py (needs SJH_TEST_DATABASE_URL)."""
import uuid

from tests.test_country_billing import BACKEND_DIR, US_IP, db_url, env  # noqa: F401  (fixtures)


def _user(env, email):
    env["db"].execute("SELECT utm_source, utm_campaign, utm_content FROM users WHERE email = %s", (email,))
    return env["db"].fetchone()


def _signup(env, **extra):
    email = f"u{uuid.uuid4().hex[:8]}@example.com"
    body = {"full_name": "Test User", "email": email, "password": "password123", **extra}
    resp = env["client"].post("/api/auth/register", json=body, headers={"X-Real-IP": US_IP})
    assert resp.status_code == 201, resp.get_json()
    return email


def test_register_stores_utm(env):
    email = _signup(env, utm_source="meta", utm_campaign="india_launch", utm_content="date_night")
    assert _user(env, email) == ("meta", "india_launch", "date_night")


def test_register_partial_utm(env):
    email = _signup(env, utm_source="instagram", utm_campaign="bio")
    assert _user(env, email) == ("instagram", "bio", None)


def test_register_without_utm_is_blank(env):
    email = _signup(env)
    assert _user(env, email) == (None, None, None)


def test_utm_values_are_cleaned(env):
    email = _signup(env, utm_source="  tgs\n\x00 ", utm_campaign="x" * 300, utm_content="")
    src, camp, content = _user(env, email)
    assert src == "tgs" and len(camp) == 100 and content is None


def test_google_signup_stores_utm(env, monkeypatch):
    import routes.auth as auth_routes
    env["app"].config["GOOGLE_CLIENT_ID"] = "test-client"
    email = f"g{uuid.uuid4().hex[:8]}@example.com"
    monkeypatch.setattr(auth_routes.google_id_token, "verify_oauth2_token",
                        lambda cred, req, cid: {"sub": "gid-" + email, "email": email,
                                                "email_verified": True, "name": "Google User"})
    resp = env["client"].post("/api/auth/google", headers={"X-Real-IP": US_IP},
                              json={"credential": "x", "utm_source": "tgs", "utm_campaign": "jobs_post",
                                    "utm_content": "nov05"})
    assert resp.status_code in (200, 201), resp.get_json()
    assert _user(env, email) == ("tgs", "jobs_post", "nov05")
    # Logging in again through a different link doesn't change the stored first touch.
    resp = env["client"].post("/api/auth/google", headers={"X-Real-IP": US_IP},
                              json={"credential": "x", "utm_source": "meta", "utm_campaign": "other"})
    assert resp.status_code == 200
    assert _user(env, email) == ("tgs", "jobs_post", "nov05")


def test_startup_adds_missing_columns(env):
    import app as app_module
    env["db"].execute("ALTER TABLE users DROP COLUMN utm_source, DROP COLUMN utm_campaign, DROP COLUMN utm_content")
    app_module.create_app()
    env["db"].execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' AND column_name LIKE 'utm_%%'")
    assert sorted(r[0] for r in env["db"].fetchall()) == ["utm_campaign", "utm_content", "utm_source"]
