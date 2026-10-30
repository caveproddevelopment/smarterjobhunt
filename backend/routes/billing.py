import json
import time
from datetime import datetime, timezone

import stripe
from flask import Blueprint, current_app, g, jsonify, request

import razorpay_client
from auth_utils import require_auth
from countries import normalize_country
from db.connection import get_cursor
from ip_country import decide_billing_country, detect_request_country
from email_utils import send_cancellation_email, send_payment_setup_email, send_plan_change_email

bp = Blueprint("billing", __name__, url_prefix="/api/billing")


@bp.before_request
def _set_stripe_key():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]


def _price_id_for(interval):
    # Weekly is the only plan offered.
    return {
        "week": current_app.config["STRIPE_PRICE_WEEKLY"],
    }.get(interval)


TRIAL_DAYS = 7
# Razorpay needs a fixed number of billing cycles; 520 weekly cycles is ten
# years, i.e. "until cancelled" in practice (the hard cap is 100 years).
RAZORPAY_TOTAL_WEEKLY_CYCLES = 520

# Statuses that mean "no live subscription" -- the user may start a new one.
ENDED_STATUSES = {"canceled", "incomplete", "incomplete_expired"}


def _plan_label(interval):
    """'week' (Stripe's recurring.interval, also what we store in
    users.billing_interval) -> a human label for emails."""
    return {"week": "Weekly"}.get(interval, interval)


def _provider_for(user, chosen_country):
    """('stripe' | 'razorpay' | None, billing_country) for a checkout.

    Anyone who already has a Stripe customer stays on Stripe. Otherwise the
    billing country decides: India -> Razorpay (when it's configured),
    everywhere else -> Stripe. The billing country is the one saved at
    sign-up; for accounts made before that existed (or Google sign-ups
    behind a VPN), work it out now from this request's IP, falling back to
    the country sent with this checkout. None = still unknown -- the
    frontend must ask the user and retry with {"country": "XX"}."""
    if user["stripe_customer_id"] or user["payment_provider"] == "stripe":
        return "stripe", user["billing_country"]

    billing_country = user["billing_country"]
    if billing_country is None:
        detected = detect_request_country()
        billing_country = decide_billing_country(
            detected["country"], detected["is_vpn"], chosen_country or user["country"]
        )
        if billing_country is None:
            return None, None

    if billing_country == "IN" and razorpay_client.is_configured():
        return "razorpay", billing_country
    return "stripe", billing_country


@bp.post("/checkout")
@require_auth
def create_checkout_session():
    """Start checkout for the weekly plan -- used both for the mandatory
    subscribe-at-registration flow (see routes/auth.py's register(), which
    logs the new user in and the frontend immediately calls this) and for
    anyone re-subscribing later from Pricing/Profile. Every new subscription
    includes a 7-day free trial.

    Users in India go to Razorpay, everyone else to Stripe (_provider_for).
    Responses:
      {"provider": "stripe", "url": ...}            -> redirect the browser
      {"provider": "razorpay", "key_id", "subscription_id", ...}
                                                    -> open Razorpay Checkout
      409 {"code": "country_required"}              -> ask for the country,
                                                       retry with {"country"}"""
    body = request.get_json(silent=True) or {}
    interval = body.get("interval", "week")
    price_id = _price_id_for(interval)
    if price_id is None:
        return jsonify({"error": "interval must be 'week'"}), 400

    chosen_country = normalize_country(body.get("country"))
    if body.get("country") and chosen_country is None:
        return jsonify({"error": "Unknown country"}), 400

    cur = get_cursor()
    cur.execute(
        """
        SELECT email, full_name, country, billing_country, payment_provider,
               stripe_customer_id, stripe_subscription_id,
               razorpay_subscription_id, subscription_status
        FROM users WHERE id = %s
        """,
        (g.user_id,),
    )
    user = cur.fetchone()
    if user is None:
        return jsonify({"error": "User not found"}), 404
    has_live_subscription = (
        (user["stripe_subscription_id"] or user["razorpay_subscription_id"])
        and user["subscription_status"] not in ENDED_STATUSES
    )
    if has_live_subscription:
        return jsonify({"error": "You already have a subscription. Manage it from your profile."}), 409

    provider, billing_country = _provider_for(user, chosen_country)
    if provider is None:
        return jsonify(
            {"error": "Please choose your country to continue.", "code": "country_required"}
        ), 409

    if billing_country and billing_country != user["billing_country"]:
        cur.execute(
            """
            UPDATE users SET billing_country = %s, country = COALESCE(country, %s)
            WHERE id = %s
            """,
            (billing_country, chosen_country, g.user_id),
        )
        cur.connection.commit()

    if provider == "razorpay":
        return _start_razorpay_checkout(cur, user)

    customer_id = user["stripe_customer_id"]

    def _create_customer():
        customer = stripe.Customer.create(
            email=user["email"], metadata={"user_id": str(g.user_id)}
        )
        cur.execute(
            "UPDATE users SET stripe_customer_id = %s WHERE id = %s",
            (customer.id, g.user_id),
        )
        cur.connection.commit()
        return customer.id

    try:
        if customer_id is None:
            customer_id = _create_customer()

        frontend_origin = current_app.config["FRONTEND_ORIGIN"]
        try:
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                client_reference_id=str(g.user_id),
                payment_method_collection="always",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{frontend_origin}/profile?checkout=success",
                cancel_url=f"{frontend_origin}/profile?checkout=cancelled",
                subscription_data={
                    "trial_period_days": 7,
                    "metadata": {"user_id": str(g.user_id)},
                },
            )
        except stripe.error.InvalidRequestError as e:
            # The stored customer_id doesn't exist on Stripe's side anymore --
            # most commonly because it's a leftover test-mode ID from before a
            # switch to live mode (test and live customers are entirely
            # separate), or because the customer was deleted directly in the
            # Stripe dashboard. Either way, self-heal by minting a fresh
            # customer and retrying once, instead of leaving the account
            # permanently stuck unable to check out.
            if getattr(e, "code", None) != "resource_missing":
                raise
            customer_id = _create_customer()
            session = stripe.checkout.Session.create(
                mode="subscription",
                customer=customer_id,
                client_reference_id=str(g.user_id),
                payment_method_collection="always",
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{frontend_origin}/profile?checkout=success",
                cancel_url=f"{frontend_origin}/profile?checkout=cancelled",
                subscription_data={
                    "trial_period_days": 7,
                    "metadata": {"user_id": str(g.user_id)},
                },
            )
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"provider": "stripe", "url": session.url})


def _start_razorpay_checkout(cur, user):
    start_at = int(time.time()) + TRIAL_DAYS * 24 * 60 * 60
    try:
        subscription = razorpay_client.create_subscription(
            g.user_id, start_at, RAZORPAY_TOTAL_WEEKLY_CYCLES
        )
    except razorpay_client.RazorpayError as e:
        return jsonify({"error": str(e)}), 502

    cur.execute(
        """
        UPDATE users
        SET payment_provider = 'razorpay', razorpay_subscription_id = %s,
            subscription_status = 'incomplete', cancel_at_period_end = false
        WHERE id = %s
        """,
        (subscription["id"], g.user_id),
    )
    cur.connection.commit()

    return jsonify(
        {
            "provider": "razorpay",
            "key_id": current_app.config["RAZORPAY_KEY_ID"],
            "subscription_id": subscription["id"],
            "trial_ends_at": datetime.fromtimestamp(start_at, tz=timezone.utc).isoformat(),
            "prefill": {"name": user["full_name"], "email": user["email"]},
        }
    )


@bp.post("/portal")
@require_auth
def create_portal_session():
    """Open Stripe's hosted portal so the user can change plans, update their
    card, or cancel — no need to build any of that ourselves."""
    cur = get_cursor()
    cur.execute(
        "SELECT stripe_customer_id, payment_provider FROM users WHERE id = %s", (g.user_id,)
    )
    user = cur.fetchone()
    if user and user["payment_provider"] == "razorpay":
        # Razorpay has no hosted customer portal -- the Profile page shows a
        # Cancel button instead (POST /api/billing/razorpay/cancel).
        return jsonify(
            {"error": "Your subscription is billed through Razorpay.", "code": "razorpay"}
        ), 400
    if user is None or user["stripe_customer_id"] is None:
        return jsonify({"error": "No billing account on file yet — subscribe first."}), 400
    portal_configuration = current_app.config.get("STRIPE_PORTAL_CONFIGURATION")
    if not portal_configuration:
        return jsonify({"error": "Billing management is not configured yet."}), 503

    frontend_origin = current_app.config["FRONTEND_ORIGIN"]
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
            configuration=portal_configuration,
            return_url=f"{frontend_origin}/profile",
        )
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"url": portal_session.url})


@bp.post("/webhook")
def webhook():
    """Stripe calls this directly (not the browser), so there's no auth
    header — the request is authenticated instead by verifying it was
    actually signed by Stripe, using the raw body."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature", "")
    webhook_secret = current_app.config["STRIPE_WEBHOOK_SECRET"]

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({"error": "Invalid payload or signature"}), 400

    event_type = event["type"]
    # This SDK's StripeObject has no .keys() or .get() — only bracket access
    # and attribute access. .to_dict() is its own recursive serializer and
    # is the correct way to get a plain, nested dict that .get() works on
    # everywhere downstream. (Plain dict(...) does NOT work here — without
    # .keys() it falls back to sequence-of-pairs iteration and breaks.)
    data = event["data"]["object"].to_dict()

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type == "customer.subscription.created":
        # Already covered by checkout.session.completed above (every
        # subscription in this app is created via Checkout) -- apply the
        # data again for safety/idempotency, but don't fire a second
        # "welcome" email for the same signup.
        _handle_subscription_updated(data, is_new=True)
    elif event_type == "customer.subscription.updated":
        _handle_subscription_updated(data, is_new=False)
    elif event_type == "customer.subscription.deleted":
        _handle_subscription_deleted(data)
    # Other event types (invoice.*, payment_intent.*, ...) aren't needed —
    # subscription status changes (including payment failures moving a sub to
    # past_due/unpaid) already arrive via customer.subscription.updated.

    return jsonify({"received": True})


def _find_user_id(customer_id, metadata):
    """Prefer the user_id we stamped into metadata; fall back to looking the
    customer up by their saved Stripe customer id."""
    user_id = (metadata or {}).get("user_id")
    if user_id:
        return int(user_id)

    if not customer_id:
        return None

    cur = get_cursor()
    cur.execute("SELECT id FROM users WHERE stripe_customer_id = %s", (customer_id,))
    row = cur.fetchone()
    return row["id"] if row else None


def _get_user_contact(user_id):
    """email/full_name for firing billing emails. Returns (None, None) if
    the user has since been deleted."""
    cur = get_cursor()
    cur.execute("SELECT email, full_name FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if not row:
        return None, None
    return row["email"], row["full_name"]


def _interval_from_subscription(subscription):
    try:
        return subscription["items"]["data"][0]["price"]["recurring"]["interval"]
    except (KeyError, IndexError, TypeError):
        return None


def _handle_checkout_completed(session):
    user_id = _find_user_id(
        session.get("customer"), {"user_id": session.get("client_reference_id")}
    )
    subscription_id = session.get("subscription")
    if user_id is None or subscription_id is None:
        return

    # Same .to_dict() treatment — stripe.Subscription.retrieve() returns a
    # live StripeObject, not a plain dict.
    subscription = stripe.Subscription.retrieve(subscription_id).to_dict()
    cur = get_cursor()
    cur.execute("SELECT stripe_subscription_id FROM users WHERE id = %s", (user_id,))
    current = cur.fetchone()
    already_applied = current and current["stripe_subscription_id"] == subscription_id
    _apply_subscription(user_id, session.get("customer"), subscription)

    email, name = _get_user_contact(user_id)
    if email and not already_applied:
        send_payment_setup_email(email, name, _plan_label(_interval_from_subscription(subscription)))


def _handle_subscription_updated(subscription, is_new=False):
    user_id = _find_user_id(subscription.get("customer"), subscription.get("metadata"))
    if user_id is None:
        return

    old_interval = None
    if not is_new:
        cur = get_cursor()
        cur.execute("SELECT billing_interval FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        old_interval = row["billing_interval"] if row else None

    _apply_subscription(user_id, subscription.get("customer"), subscription)

    if is_new:
        return

    # Only "customer.subscription.updated" (not "created") reaches here, so
    # this fires for every update -- renewals, status changes, plan swaps.
    # Only email when the billing interval actually changed, so a payment
    # retry or renewal doesn't look like a plan change to the user.
    new_interval = _interval_from_subscription(subscription)
    if old_interval and new_interval and old_interval != new_interval:
        email, name = _get_user_contact(user_id)
        if email:
            send_plan_change_email(email, name, _plan_label(old_interval), _plan_label(new_interval))


def _handle_subscription_deleted(subscription):
    user_id = _find_user_id(subscription.get("customer"), subscription.get("metadata"))
    if user_id is None:
        return

    cur = get_cursor()
    cur.execute(
        "SELECT email, full_name, billing_interval, current_period_end FROM users WHERE id = %s",
        (user_id,),
    )
    user = cur.fetchone()

    cur.execute(
        """
        UPDATE users
        SET plan = 'free', subscription_status = 'canceled', stripe_subscription_id = NULL,
            billing_interval = NULL, current_period_end = NULL, cancel_at_period_end = false
        WHERE id = %s
        """,
        (user_id,),
    )
    cur.connection.commit()

    if user and user["email"]:
        end_date = (
            user["current_period_end"].strftime("%B %-d, %Y")
            if user["current_period_end"] else None
        )
        send_cancellation_email(
            user["email"], user["full_name"], _plan_label(user["billing_interval"]), end_date
        )


def _apply_subscription(user_id, customer_id, subscription):
    status = subscription.get("status")
    interval = _interval_from_subscription(subscription)
    # current_period_end has moved off the top-level Subscription object in
    # newer API versions (it now lives per subscription item, under
    # items.data[0].current_period_end) — fall back there if it's missing.
    period_end = subscription.get("current_period_end")
    if period_end is None:
        try:
            period_end = subscription["items"]["data"][0]["current_period_end"]
        except (KeyError, IndexError, TypeError):
            period_end = None
    period_end_dt = datetime.fromtimestamp(period_end, tz=timezone.utc) if period_end else None
    plan = "pro" if status in ("active", "trialing") else "free"

    cur = get_cursor()
    cur.execute(
        """
        UPDATE users
        SET plan = %s, subscription_status = %s, payment_provider = 'stripe',
            stripe_customer_id = COALESCE(stripe_customer_id, %s),
            stripe_subscription_id = %s, billing_interval = %s, current_period_end = %s,
            cancel_at_period_end = %s
        WHERE id = %s
        """,
        (
            plan, status, customer_id, subscription.get("id"), interval, period_end_dt,
            bool(subscription.get("cancel_at_period_end")), user_id,
        ),
    )
    cur.connection.commit()

# ---------------------------------------------------------------------------
# Razorpay (users in India). Same weekly plan + 7-day trial as Stripe, so it
# writes the same plan / subscription_status / billing_interval /
# current_period_end columns, and the rest of the app doesn't need to know
# which provider a user is on.
# ---------------------------------------------------------------------------

# Razorpay subscription status -> the Stripe-style status we store.
RAZORPAY_STATUS_MAP = {
    "created": "incomplete",        # checkout opened, mandate not authorized yet
    "authenticated": "trialing",    # mandate authorized; first charge at start_at
    "active": "active",
    "pending": "past_due",          # a charge failed; Razorpay is retrying
    "halted": "unpaid",             # retries exhausted
    "paused": "paused",
    "cancelled": "canceled",
    "completed": "canceled",
    "expired": "incomplete_expired",
}


@bp.post("/razorpay/verify")
@require_auth
def razorpay_verify():
    """Called by the frontend from Razorpay Checkout's success handler.
    Checks the payment signature, then pulls the subscription from Razorpay
    and applies it -- so the user has access straight away instead of
    waiting for the webhook (which will apply the same state again)."""
    if not razorpay_client.is_configured():
        return jsonify({"error": "Razorpay is not configured"}), 503
    body = request.get_json(silent=True) or {}
    payment_id = body.get("razorpay_payment_id")
    subscription_id = body.get("razorpay_subscription_id")
    signature = body.get("razorpay_signature")

    if not razorpay_client.verify_checkout_signature(payment_id, subscription_id, signature):
        return jsonify({"error": "Payment verification failed"}), 400

    cur = get_cursor()
    cur.execute("SELECT razorpay_subscription_id FROM users WHERE id = %s", (g.user_id,))
    user = cur.fetchone()
    if user is None or user["razorpay_subscription_id"] != subscription_id:
        return jsonify({"error": "That subscription doesn't belong to this account"}), 400

    try:
        subscription = razorpay_client.fetch_subscription(subscription_id)
    except razorpay_client.RazorpayError as e:
        return jsonify({"error": str(e)}), 502

    _apply_razorpay_subscription(g.user_id, subscription)
    cur.execute(
        "SELECT plan, subscription_status, current_period_end FROM users WHERE id = %s",
        (g.user_id,),
    )
    return jsonify(cur.fetchone())


@bp.post("/razorpay/cancel")
@require_auth
def razorpay_cancel():
    """Razorpay has no customer portal, so the Profile page calls this.

    Paid weeks are cancelled at the end of the current cycle (access until
    then). During the free trial Razorpay only allows an immediate cancel --
    no charge is ever made -- but the user keeps access until the trial's
    end date, same as cancelling a Stripe trial (expire_lapsed_access in
    auth_utils.py switches plan back to 'free' after that)."""
    if not razorpay_client.is_configured():
        return jsonify({"error": "Razorpay is not configured"}), 503
    cur = get_cursor()
    cur.execute(
        """
        SELECT email, full_name, payment_provider, razorpay_subscription_id,
               subscription_status, current_period_end, billing_interval
        FROM users WHERE id = %s
        """,
        (g.user_id,),
    )
    user = cur.fetchone()
    if (
        user is None
        or user["payment_provider"] != "razorpay"
        or not user["razorpay_subscription_id"]
        or user["subscription_status"] in ENDED_STATUSES
    ):
        return jsonify({"error": "No active Razorpay subscription to cancel"}), 400

    subscription_id = user["razorpay_subscription_id"]
    try:
        live = razorpay_client.fetch_subscription(subscription_id)
        in_trial = live.get("status") in ("created", "authenticated")
        cancelled = razorpay_client.cancel_subscription(subscription_id, at_cycle_end=not in_trial)
    except razorpay_client.RazorpayError as e:
        return jsonify({"error": str(e)}), 502

    if in_trial:
        # Immediate cancel on Razorpay's side; access runs to the trial end.
        trial_end = _ts(live.get("start_at"))
        cur.execute(
            """
            UPDATE users
            SET subscription_status = 'canceled', cancel_at_period_end = true,
                current_period_end = COALESCE(%s, current_period_end),
                plan = CASE WHEN COALESCE(%s, current_period_end) > now() THEN 'pro' ELSE 'free' END
            WHERE id = %s
            """,
            (trial_end, trial_end, g.user_id),
        )
    else:
        # Still active until the cycle ends; the 'subscription.cancelled'
        # webhook then switches the user to free.
        _apply_razorpay_subscription(g.user_id, cancelled)
        cur.execute(
            "UPDATE users SET cancel_at_period_end = true WHERE id = %s", (g.user_id,)
        )
    cur.connection.commit()

    cur.execute(
        "SELECT plan, subscription_status, current_period_end, cancel_at_period_end FROM users WHERE id = %s",
        (g.user_id,),
    )
    updated = cur.fetchone()
    if user["email"]:
        end_date = (
            updated["current_period_end"].strftime("%B %-d, %Y")
            if updated["current_period_end"] else None
        )
        send_cancellation_email(
            user["email"], user["full_name"], _plan_label(user["billing_interval"] or "week"), end_date
        )
    return jsonify(updated)


@bp.post("/razorpay/webhook")
def razorpay_webhook():
    """Razorpay calls this directly. Authenticated by the
    X-Razorpay-Signature HMAC of the raw body (RAZORPAY_WEBHOOK_SECRET).
    Subscribe the webhook to the subscription.* events."""
    raw_body = request.get_data()
    signature = request.headers.get("X-Razorpay-Signature", "")
    if not razorpay_client.verify_webhook_signature(raw_body, signature):
        return jsonify({"error": "Invalid signature"}), 400

    try:
        event = json.loads(raw_body)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400

    event_type = event.get("event") or ""
    entity = (((event.get("payload") or {}).get("subscription") or {}).get("entity")) or {}
    if not event_type.startswith("subscription.") or not entity.get("id"):
        return jsonify({"received": True})

    user_id = _find_razorpay_user(entity)
    if user_id is None:
        return jsonify({"received": True})

    cur = get_cursor()
    cur.execute(
        "SELECT plan, subscription_status, razorpay_subscription_id FROM users WHERE id = %s",
        (user_id,),
    )
    before = cur.fetchone()
    # Only the user's current subscription counts -- ignore late events for
    # an older checkout attempt they abandoned.
    if before is None or before["razorpay_subscription_id"] != entity["id"]:
        return jsonify({"received": True})

    _apply_razorpay_subscription(user_id, entity)

    cur.execute("SELECT plan, subscription_status, billing_interval FROM users WHERE id = %s", (user_id,))
    after = cur.fetchone()
    newly_started = (
        before["subscription_status"] in (None, "incomplete")
        and after["subscription_status"] in ("trialing", "active")
    )
    if newly_started:
        email, name = _get_user_contact(user_id)
        if email:
            send_payment_setup_email(email, name, _plan_label("week"))

    return jsonify({"received": True})


def _find_razorpay_user(entity):
    user_id = (entity.get("notes") or {}).get("user_id")
    if user_id:
        try:
            return int(user_id)
        except (TypeError, ValueError):
            pass
    cur = get_cursor()
    cur.execute("SELECT id FROM users WHERE razorpay_subscription_id = %s", (entity.get("id"),))
    row = cur.fetchone()
    return row["id"] if row else None


def _ts(value):
    return datetime.fromtimestamp(int(value), tz=timezone.utc) if value else None


def _apply_razorpay_subscription(user_id, entity):
    raw_status = entity.get("status")
    status = RAZORPAY_STATUS_MAP.get(raw_status, raw_status)

    if raw_status in ("created", "authenticated"):
        period_end = _ts(entity.get("start_at"))          # trial ends at the first charge
    elif raw_status in ("active", "pending", "halted", "paused"):
        period_end = _ts(entity.get("current_end") or entity.get("charge_at"))
    else:
        period_end = None                                  # keep what we had

    cur = get_cursor()
    cur.execute(
        """
        UPDATE users
        SET payment_provider = 'razorpay',
            subscription_status = %(status)s,
            razorpay_customer_id = COALESCE(%(customer_id)s, razorpay_customer_id),
            billing_interval = 'week',
            current_period_end = COALESCE(%(period_end)s, current_period_end),
            plan = CASE
                WHEN %(status)s IN ('trialing', 'active') THEN 'pro'
                -- Cancelled with time left (e.g. a cancelled trial): keep
                -- access until then; expire_lapsed_access() ends it later.
                WHEN %(status)s = 'canceled'
                     AND COALESCE(%(period_end)s, current_period_end) > now() THEN 'pro'
                ELSE 'free' END
        WHERE id = %(user_id)s
        """,
        {
            "status": status,
            "customer_id": entity.get("customer_id"),
            "period_end": period_end,
            "user_id": user_id,
        },
    )
    cur.connection.commit()
