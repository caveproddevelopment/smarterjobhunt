"""End-to-end tests for country detection, Stripe/Razorpay routing and the
saved last search, against a real Postgres.

Skipped unless SJH_TEST_DATABASE_URL points at a server where this user may
CREATE DATABASE. Each run creates and drops its own throwaway database and
applies db/schema.sql to it -- nothing else is touched. Never point this at
production. Network calls (ipapi.is, Razorpay, Stripe) are all faked.

    cd backend
    SJH_TEST_DATABASE_URL=postgresql://postgres@localhost:5432/postgres python -m pytest tests -q
"""
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import pytest

psycopg2 = pytest.importorskip("psycopg2")

BASE_URL = os.environ.get("SJH_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not BASE_URL, reason="SJH_TEST_DATABASE_URL not set")

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_SECRET = "rzp_secret_test"
WEBHOOK_SECRET = "rzp_webhook_test"

INDIA_IP = "49.36.10.10"
US_IP = "8.8.4.4"
VPN_IP = "185.1.1.1"
IP_TABLE = {
    INDIA_IP: {"location": {"country_code": "IN"}, "is_vpn": False},
    US_IP: {"location": {"country_code": "US"}, "is_vpn": False},
    VPN_IP: {"location": {"country_code": "NL"}, "is_vpn": True},
}


def _with_db(url, dbname):
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path="/" + dbname))


@pytest.fixture(scope="module")
def db_url():
    dbname = f"sjh_test_{uuid.uuid4().hex[:10]}"
    admin = psycopg2.connect(BASE_URL)
    admin.autocommit = True
    admin.cursor().execute(f"CREATE DATABASE {dbname}")
    url = _with_db(BASE_URL, dbname)
    conn = psycopg2.connect(url)
    conn.autocommit = True
    with open(os.path.join(BACKEND_DIR, "db", "schema.sql")) as f:
        conn.cursor().execute(f.read())
    conn.close()
    yield url
    admin.cursor().execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")
    admin.close()


class FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status
        self.text = json.dumps(data)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("requests").HTTPError(str(self.status_code))


class FakeRazorpay:
    """Stands in for api.razorpay.com: keeps subscriptions in a dict."""

    def __init__(self):
        self.subs = {}
        self.calls = []

    def __call__(self, method, url, auth=None, json=None, timeout=None):
        path = url.split("/v1", 1)[1]
        self.calls.append((method, path, json))
        if method == "POST" and path == "/subscriptions":
            sid = f"sub_{uuid.uuid4().hex[:12]}"
            self.subs[sid] = {
                "id": sid, "status": "created", "start_at": json["start_at"],
                "notes": json["notes"], "customer_id": None, "current_end": None,
            }
            return FakeResponse(dict(self.subs[sid]))
        if method == "GET" and path.startswith("/subscriptions/"):
            return FakeResponse(dict(self.subs[path.rsplit("/", 1)[1]]))
        if method == "POST" and path.endswith("/cancel"):
            sid = path.split("/")[2]
            sub = self.subs[sid]
            if json["cancel_at_cycle_end"] and sub["status"] != "active":
                return FakeResponse({"error": {"description": "no billing cycle"}}, 400)
            if not json["cancel_at_cycle_end"]:
                sub["status"] = "cancelled"
            return FakeResponse(dict(sub))
        return FakeResponse({"error": {"description": "unexpected"}}, 404)


@pytest.fixture()
def env(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    for key in ("RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_PLAN_ID_WEEKLY",
                "RAZORPAY_WEBHOOK_SECRET", "STRIPE_PRICE_WEEKLY", "STRIPE_SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)
    sys.path.insert(0, BACKEND_DIR)
    for mod in list(sys.modules):
        if mod in ("app", "config", "ip_country", "razorpay_client", "auth_utils", "countries") or \
                mod.startswith("routes") or mod.startswith("db"):
            del sys.modules[mod]
    import app as app_module
    import ip_country
    import razorpay_client

    flask_app = app_module.create_app()
    flask_app.config.update(
        TESTING=True, STRIPE_PRICE_WEEKLY="price_week", STRIPE_SECRET_KEY="sk_test",
        RAZORPAY_KEY_ID="rzp_test_key", RAZORPAY_KEY_SECRET=KEY_SECRET,
        RAZORPAY_PLAN_ID_WEEKLY="plan_inr_week", RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET,
    )
    ip_country._CACHE.clear()
    monkeypatch.setattr(
        ip_country.requests, "get",
        lambda url, params=None, timeout=None: FakeResponse(IP_TABLE.get(params["q"], {})),
    )
    fake_rzp = FakeRazorpay()
    monkeypatch.setattr(razorpay_client.requests, "request", fake_rzp)

    import stripe
    stripe_calls = []
    monkeypatch.setattr(stripe.Customer, "create",
                        lambda **kw: type("C", (), {"id": "cus_123"})())
    def fake_session(**kw):
        stripe_calls.append(kw)
        return type("S", (), {"url": "https://checkout.stripe.test/s"})()
    monkeypatch.setattr(stripe.checkout.Session, "create", fake_session)

    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    return {"app": flask_app, "client": flask_app.test_client(), "rzp": fake_rzp,
            "stripe_calls": stripe_calls, "db": conn.cursor()}


def _register(client, ip, country=None):
    email = f"u{uuid.uuid4().hex[:8]}@example.com"
    body = {"full_name": "Test User", "email": email, "password": "password123"}
    if country:
        body["country"] = country
    resp = client.post("/api/auth/register", json=body, headers={"X-Real-IP": ip})
    assert resp.status_code == 201, resp.get_json()
    data = resp.get_json()
    return data["user"]["id"], {"Authorization": f"Bearer {data['token']}", "X-Real-IP": ip}


def _row(env, user_id, *cols):
    env["db"].execute(f"SELECT {', '.join(cols)} FROM users WHERE id = %s", (user_id,))
    return dict(zip(cols, env["db"].fetchone()))


def _sig(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


# --- country detection -------------------------------------------------------

def test_geo_suggests_ip_country_but_not_for_vpn(env):
    data = env["client"].get("/api/geo", headers={"X-Real-IP": INDIA_IP}).get_json()
    assert data["suggested_country"] == "IN" and data["is_vpn"] is False
    assert {"code": "IN", "name": "India"} in data["countries"]
    data = env["client"].get("/api/geo", headers={"X-Real-IP": VPN_IP}).get_json()
    assert data["suggested_country"] is None and data["is_vpn"] is True


def test_trusted_ip_country_wins_over_picked_country(env):
    user_id, _ = _register(env["client"], INDIA_IP, country="US")
    row = _row(env, user_id, "country", "signup_ip_country", "signup_ip_is_vpn", "billing_country")
    assert row == {"country": "US", "signup_ip_country": "IN",
                   "signup_ip_is_vpn": False, "billing_country": "IN"}


def test_vpn_falls_back_to_picked_country(env):
    user_id, _ = _register(env["client"], VPN_IP, country="IN")
    row = _row(env, user_id, "signup_ip_is_vpn", "billing_country")
    assert row == {"signup_ip_is_vpn": True, "billing_country": "IN"}


def test_spoofed_left_most_forwarded_for_is_ignored(env):
    user_id, _ = _register(env["client"], US_IP, country="US")
    resp = env["client"].get(
        "/api/geo", headers={"X-Forwarded-For": f"{INDIA_IP}, {US_IP}"}
    ).get_json()
    assert resp["suggested_country"] == "US"


def test_invalid_country_rejected(env):
    resp = env["client"].post("/api/auth/register", json={
        "full_name": "Test User", "email": "bad@example.com", "password": "password123",
        "country": "XX"}, headers={"X-Real-IP": US_IP})
    assert resp.status_code == 400


# --- checkout routing --------------------------------------------------------

def test_india_goes_to_razorpay_with_7_day_trial(env):
    user_id, headers = _register(env["client"], INDIA_IP, country="IN")
    resp = env["client"].post("/api/billing/checkout", json={"interval": "week"}, headers=headers)
    data = resp.get_json()
    assert resp.status_code == 200, data
    assert data["provider"] == "razorpay" and data["key_id"] == "rzp_test_key"
    method, path, payload = env["rzp"].calls[-1]
    assert (method, path) == ("POST", "/subscriptions")
    assert payload["plan_id"] == "plan_inr_week" and payload["notes"] == {"user_id": str(user_id)}
    assert abs(payload["start_at"] - (time.time() + 7 * 86400)) < 60
    row = _row(env, user_id, "payment_provider", "razorpay_subscription_id", "subscription_status", "plan")
    assert row["payment_provider"] == "razorpay" and row["razorpay_subscription_id"] == data["subscription_id"]
    assert row["subscription_status"] == "incomplete" and row["plan"] == "free"


def test_rest_of_world_goes_to_stripe(env):
    user_id, headers = _register(env["client"], US_IP, country="US")
    data = env["client"].post("/api/billing/checkout", json={}, headers=headers).get_json()
    assert data == {"provider": "stripe", "url": "https://checkout.stripe.test/s"}
    assert env["stripe_calls"][-1]["subscription_data"]["trial_period_days"] == 7


def test_india_falls_back_to_stripe_until_razorpay_configured(env):
    env["app"].config["RAZORPAY_PLAN_ID_WEEKLY"] = None
    _, headers = _register(env["client"], INDIA_IP, country="IN")
    data = env["client"].post("/api/billing/checkout", json={}, headers=headers).get_json()
    assert data["provider"] == "stripe"


def test_existing_stripe_customer_in_india_stays_on_stripe(env):
    user_id, headers = _register(env["client"], INDIA_IP, country="IN")
    env["db"].execute("UPDATE users SET stripe_customer_id = 'cus_old' WHERE id = %s", (user_id,))
    data = env["client"].post("/api/billing/checkout", json={}, headers=headers).get_json()
    assert data["provider"] == "stripe"


def test_unknown_country_asks_then_routes(env):
    user_id, headers = _register(env["client"], VPN_IP)  # e.g. Google sign-up behind a VPN
    assert _row(env, user_id, "billing_country")["billing_country"] is None
    resp = env["client"].post("/api/billing/checkout", json={}, headers=headers)
    assert resp.status_code == 409 and resp.get_json()["code"] == "country_required"
    resp = env["client"].post("/api/billing/checkout", json={"country": "IN"}, headers=headers)
    assert resp.get_json()["provider"] == "razorpay"
    assert _row(env, user_id, "billing_country", "country") == {"billing_country": "IN", "country": "IN"}


def test_cannot_start_second_subscription(env):
    user_id, headers = _register(env["client"], INDIA_IP, country="IN")
    env["db"].execute(
        "UPDATE users SET razorpay_subscription_id='sub_x', subscription_status='trialing' WHERE id=%s",
        (user_id,))
    assert env["client"].post("/api/billing/checkout", json={}, headers=headers).status_code == 409


# --- Razorpay verify / webhook / cancel -------------------------------------

def _start_trial(env):
    user_id, headers = _register(env["client"], INDIA_IP, country="IN")
    sid = env["client"].post("/api/billing/checkout", json={}, headers=headers).get_json()["subscription_id"]
    env["rzp"].subs[sid].update(status="authenticated", customer_id="cust_1")
    resp = env["client"].post("/api/billing/razorpay/verify", headers=headers, json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid,
        "razorpay_signature": _sig(KEY_SECRET, f"pay_1|{sid}".encode())})
    assert resp.status_code == 200, resp.get_json()
    return user_id, headers, sid


def test_verify_unlocks_trial(env):
    user_id, _, sid = _start_trial(env)
    row = _row(env, user_id, "plan", "subscription_status", "razorpay_customer_id", "current_period_end")
    assert row["plan"] == "pro" and row["subscription_status"] == "trialing"
    assert row["razorpay_customer_id"] == "cust_1"
    expected_end = datetime.fromtimestamp(env["rzp"].subs[sid]["start_at"], tz=timezone.utc)
    assert row["current_period_end"] == expected_end


def test_verify_rejects_bad_signature(env):
    _, headers = _register(env["client"], INDIA_IP, country="IN")
    sid = env["client"].post("/api/billing/checkout", json={}, headers=headers).get_json()["subscription_id"]
    resp = env["client"].post("/api/billing/razorpay/verify", headers=headers, json={
        "razorpay_payment_id": "pay_1", "razorpay_subscription_id": sid, "razorpay_signature": "nope"})
    assert resp.status_code == 400


def _webhook(env, event, entity, secret=WEBHOOK_SECRET):
    body = json.dumps({"event": event, "payload": {"subscription": {"entity": entity}}}).encode()
    return env["client"].post("/api/billing/razorpay/webhook", data=body,
                              headers={"X-Razorpay-Signature": _sig(secret, body),
                                       "Content-Type": "application/json"})


def test_webhook_activation_and_halt(env):
    user_id, _, sid = _start_trial(env)
    end = int(time.time()) + 7 * 86400
    entity = {"id": sid, "status": "active", "current_end": end, "notes": {"user_id": str(user_id)}}
    assert _webhook(env, "subscription.charged", entity).status_code == 200
    row = _row(env, user_id, "plan", "subscription_status", "current_period_end")
    assert row["plan"] == "pro" and row["subscription_status"] == "active"
    assert row["current_period_end"] == datetime.fromtimestamp(end, tz=timezone.utc)
    _webhook(env, "subscription.halted", {**entity, "status": "halted"})
    assert _row(env, user_id, "plan", "subscription_status") == {"plan": "free", "subscription_status": "unpaid"}


def test_webhook_rejects_bad_signature_and_ignores_stale_subscription(env):
    user_id, _, sid = _start_trial(env)
    entity = {"id": sid, "status": "halted", "notes": {"user_id": str(user_id)}}
    assert _webhook(env, "subscription.halted", entity, secret="wrong").status_code == 400
    _webhook(env, "subscription.halted", {**entity, "id": "sub_old_abandoned"})
    assert _row(env, user_id, "plan")["plan"] == "pro"


def test_cancel_during_trial_keeps_access_until_trial_end(env):
    user_id, headers, sid = _start_trial(env)
    resp = env["client"].post("/api/billing/razorpay/cancel", headers=headers)
    assert resp.status_code == 200, resp.get_json()
    assert env["rzp"].calls[-1][2] == {"cancel_at_cycle_end": 0}
    row = _row(env, user_id, "plan", "subscription_status", "cancel_at_period_end")
    assert row == {"plan": "pro", "subscription_status": "canceled", "cancel_at_period_end": True}
    # A late 'cancelled' webhook must not cut the trial short either.
    _webhook(env, "subscription.cancelled", {"id": sid, "status": "cancelled", "notes": {"user_id": str(user_id)}})
    assert _row(env, user_id, "plan")["plan"] == "pro"
    # Once the trial date passes, the next request downgrades them.
    env["db"].execute("UPDATE users SET current_period_end = now() - interval '1 minute' WHERE id = %s", (user_id,))
    me = env["client"].get("/api/auth/me", headers=headers).get_json()
    assert me["plan"] == "free"


def test_cancel_paid_week_is_at_cycle_end(env):
    user_id, headers, sid = _start_trial(env)
    env["rzp"].subs[sid].update(status="active", current_end=int(time.time()) + 3 * 86400)
    resp = env["client"].post("/api/billing/razorpay/cancel", headers=headers)
    assert resp.status_code == 200, resp.get_json()
    assert env["rzp"].calls[-1][2] == {"cancel_at_cycle_end": 1}
    row = _row(env, user_id, "plan", "subscription_status", "cancel_at_period_end")
    assert row == {"plan": "pro", "subscription_status": "active", "cancel_at_period_end": True}


def test_portal_points_razorpay_users_elsewhere(env):
    _, headers, _ = _start_trial(env)
    resp = env["client"].post("/api/billing/portal", headers=headers)
    assert resp.status_code == 400 and resp.get_json()["code"] == "razorpay"


# --- last search ---------------------------------------------------------------

def test_last_search_saved_for_subscribers_on_first_page_only(env):
    user_id, headers, _ = _start_trial(env)
    client = env["client"]
    qs = "title=Data+Analyst&variant_title=Business+Analyst&variant_title=BI+Analyst&variant_title=Business+Analyst"
    assert client.get(f"/api/jobs?{qs}", headers=headers).status_code == 200
    row = _row(env, user_id, "last_search_title", "last_search_variants", "last_searched_at")
    assert row["last_search_title"] == "Data Analyst"
    assert row["last_search_variants"] == ["Business Analyst", "BI Analyst"]
    assert row["last_searched_at"] is not None
    client.get("/api/jobs?title=Nurse&offset=20", headers=headers)
    assert _row(env, user_id, "last_search_title")["last_search_title"] == "Data Analyst"
    me = client.get("/api/auth/me", headers=headers).get_json()
    assert me["last_search_title"] == "Data Analyst" and me["last_search_variants"] == ["Business Analyst", "BI Analyst"]


def test_last_search_not_saved_for_non_subscribers(env):
    user_id, headers = _register(env["client"], US_IP, country="US")
    env["client"].get("/api/jobs?title=Nurse", headers=headers)
    assert _row(env, user_id, "last_search_title")["last_search_title"] is None
