from datetime import datetime, timezone

import stripe
from flask import Blueprint, current_app, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor

bp = Blueprint("billing", __name__, url_prefix="/api/billing")


@bp.before_request
def _set_stripe_key():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]


def _price_id_for(interval):
    return {
        "week": current_app.config["STRIPE_PRICE_WEEKLY"],
        "month": current_app.config["STRIPE_PRICE_MONTHLY"],
    }.get(interval)


@bp.post("/checkout")
@require_auth
def create_checkout_session():
    """Start a Stripe Checkout session for the weekly or monthly plan and
    hand back the URL to redirect the browser to."""
    body = request.get_json(silent=True) or {}
    interval = body.get("interval")
    price_id = _price_id_for(interval)
    if price_id is None:
        return jsonify({"error": "interval must be 'week' or 'month'"}), 400

    cur = get_cursor()
    cur.execute("SELECT email, stripe_customer_id FROM users WHERE id = %s", (g.user_id,))
    user = cur.fetchone()
    if user is None:
        return jsonify({"error": "User not found"}), 404

    customer_id = user["stripe_customer_id"]

    try:
        if customer_id is None:
            customer = stripe.Customer.create(
                email=user["email"], metadata={"user_id": str(g.user_id)}
            )
            customer_id = customer.id
            cur.execute(
                "UPDATE users SET stripe_customer_id = %s WHERE id = %s",
                (customer_id, g.user_id),
            )
            cur.connection.commit()

        frontend_origin = current_app.config["FRONTEND_ORIGIN"]
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            client_reference_id=str(g.user_id),
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{frontend_origin}/profile?checkout=success",
            cancel_url=f"{frontend_origin}/profile?checkout=cancelled",
            subscription_data={"metadata": {"user_id": str(g.user_id)}},
        )
    except stripe.error.StripeError as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"url": session.url})


@bp.post("/portal")
@require_auth
def create_portal_session():
    """Open Stripe's hosted portal so the user can change plans, update their
    card, or cancel — no need to build any of that ourselves."""
    cur = get_cursor()
    cur.execute("SELECT stripe_customer_id FROM users WHERE id = %s", (g.user_id,))
    user = cur.fetchone()
    if user is None or user["stripe_customer_id"] is None:
        return jsonify({"error": "No billing account on file yet — subscribe first."}), 400

    frontend_origin = current_app.config["FRONTEND_ORIGIN"]
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
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
    # Converted to a plain dict here: the installed stripe SDK's StripeObject
    # no longer supports .get() (bracket access still works, but every
    # handler below uses .get() for safe optional-field access), so this is
    # the one place we normalize it for everything downstream.
    data = dict(event["data"]["object"])

    if event_type == "checkout.session.completed":
        _handle_checkout_completed(data)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        _handle_subscription_updated(data)
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

    # stripe.Subscription.retrieve() returns a StripeObject too — same .get()
    # issue as above, so normalize it the same way before it reaches
    # _apply_subscription().
    subscription = dict(stripe.Subscription.retrieve(subscription_id))
    _apply_subscription(user_id, session.get("customer"), subscription)


def _handle_subscription_updated(subscription):
    user_id = _find_user_id(subscription.get("customer"), subscription.get("metadata"))
    if user_id is None:
        return
    _apply_subscription(user_id, subscription.get("customer"), subscription)


def _handle_subscription_deleted(subscription):
    user_id = _find_user_id(subscription.get("customer"), subscription.get("metadata"))
    if user_id is None:
        return

    cur = get_cursor()
    cur.execute(
        """
        UPDATE users
        SET plan = 'free', subscription_status = 'canceled', stripe_subscription_id = NULL,
            billing_interval = NULL, current_period_end = NULL
        WHERE id = %s
        """,
        (user_id,),
    )
    cur.connection.commit()


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
        SET plan = %s, subscription_status = %s,
            stripe_customer_id = COALESCE(stripe_customer_id, %s),
            stripe_subscription_id = %s, billing_interval = %s, current_period_end = %s
        WHERE id = %s
        """,
        (plan, status, customer_id, subscription.get("id"), interval, period_end_dt, user_id),
    )
    cur.connection.commit()