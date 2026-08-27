from datetime import datetime, timezone

import stripe
from flask import Blueprint, current_app, g, jsonify, request

from auth_utils import require_auth
from db.connection import get_cursor
from email_utils import send_cancellation_email, send_payment_setup_email, send_plan_change_email

bp = Blueprint("billing", __name__, url_prefix="/api/billing")


@bp.before_request
def _set_stripe_key():
    stripe.api_key = current_app.config["STRIPE_SECRET_KEY"]


def _price_id_for(interval):
    return {
        "week": current_app.config["STRIPE_PRICE_WEEKLY"],
        "month": current_app.config["STRIPE_PRICE_MONTHLY"],
    }.get(interval)


def _plan_label(interval):
    """'week'/'month' (Stripe's recurring.interval, also what we store in
    users.billing_interval) -> a human label for emails."""
    return {"week": "Weekly", "month": "Monthly"}.get(interval, interval)


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
                line_items=[{"price": price_id, "quantity": 1}],
                success_url=f"{frontend_origin}/profile?checkout=success",
                cancel_url=f"{frontend_origin}/profile?checkout=cancelled",
                subscription_data={"metadata": {"user_id": str(g.user_id)}},
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
    _apply_subscription(user_id, session.get("customer"), subscription)

    email, name = _get_user_contact(user_id)
    if email:
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
            billing_interval = NULL, current_period_end = NULL
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
        SET plan = %s, subscription_status = %s,
            stripe_customer_id = COALESCE(stripe_customer_id, %s),
            stripe_subscription_id = %s, billing_interval = %s, current_period_end = %s
        WHERE id = %s
        """,
        (plan, status, customer_id, subscription.get("id"), interval, period_end_dt, user_id),
    )
    cur.connection.commit()