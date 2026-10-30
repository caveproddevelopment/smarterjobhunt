"""Minimal Razorpay REST client for the weekly subscription -- just the
handful of calls routes/billing.py needs, over plain `requests` (already a
dependency) rather than pulling in the razorpay SDK.

Docs: https://razorpay.com/docs/api/payments/subscriptions/
"""
import hashlib
import hmac
import time

import requests
from flask import current_app

API_BASE = "https://api.razorpay.com/v1"
_TIMEOUT_SECONDS = 15


class RazorpayError(Exception):
    pass


def is_configured():
    cfg = current_app.config
    return bool(
        cfg.get("RAZORPAY_KEY_ID")
        and cfg.get("RAZORPAY_KEY_SECRET")
        and cfg.get("RAZORPAY_PLAN_ID_WEEKLY")
    )


def _auth():
    cfg = current_app.config
    return (cfg["RAZORPAY_KEY_ID"], cfg["RAZORPAY_KEY_SECRET"])


def _request(method, path, payload=None):
    try:
        resp = requests.request(
            method, f"{API_BASE}{path}", auth=_auth(), json=payload, timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as e:
        raise RazorpayError(f"Could not reach Razorpay: {e}") from e
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        description = (data.get("error") or {}).get("description") or resp.text[:200]
        raise RazorpayError(description)
    return data


def create_subscription(user_id, start_at, total_count):
    """Weekly subscription whose first charge is at `start_at` (unix
    seconds) -- the 7-day free trial. Until then the customer only
    authorizes the mandate in Checkout and the subscription sits in
    'authenticated'. Razorpay has no customer_id input here -- it creates
    and links the customer itself when the mandate is authorized, and the
    subscription entity carries customer_id from then on."""
    return _request(
        "POST",
        "/subscriptions",
        {
            "plan_id": current_app.config["RAZORPAY_PLAN_ID_WEEKLY"],
            "total_count": total_count,
            "quantity": 1,
            "start_at": int(start_at),
            # Abandoned checkouts: the mandate must be authorized within a
            # day, after which Razorpay expires the subscription instead of
            # leaving it open for the default 30 years.
            "expire_by": int(time.time()) + 24 * 60 * 60,
            "customer_notify": 1,
            "notes": {"user_id": str(user_id)},
        },
    )


def fetch_subscription(subscription_id):
    return _request("GET", f"/subscriptions/{subscription_id}")


def cancel_subscription(subscription_id, at_cycle_end):
    return _request(
        "POST",
        f"/subscriptions/{subscription_id}/cancel",
        {"cancel_at_cycle_end": 1 if at_cycle_end else 0},
    )


def _hmac_hex(secret, message):
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_checkout_signature(payment_id, subscription_id, signature):
    """Checkout's success handler returns razorpay_signature =
    HMAC_SHA256(payment_id + '|' + subscription_id, key_secret)."""
    if not (payment_id and subscription_id and signature):
        return False
    expected = _hmac_hex(
        current_app.config["RAZORPAY_KEY_SECRET"], f"{payment_id}|{subscription_id}".encode()
    )
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(raw_body, signature):
    """X-Razorpay-Signature = HMAC_SHA256(raw request body, webhook secret)."""
    secret = current_app.config.get("RAZORPAY_WEBHOOK_SECRET")
    if not (secret and signature):
        return False
    return hmac.compare_digest(_hmac_hex(secret, raw_body), signature)
