import re

import psycopg2
from flask import Blueprint, current_app, g, jsonify, redirect, request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import (
    issue_email_change_token,
    issue_password_reset_token,
    issue_token,
    issue_verification_token,
    require_auth,
    verify_email_change_token,
    verify_password_reset_token,
    verify_verification_token,
)
from db.connection import get_cursor
from email_utils import (
    send_email_change_confirmation,
    send_password_reset_email,
    send_verification_email,
)

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Letters and single spaces between words (e.g. "John Smith"). No leading/
# trailing space, no double spaces, no digits or punctuation.
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z]+( [A-Za-z]+)*$")

# Fields returned for a logged-in user everywhere (login, /me, /google).
# has_password lets the frontend know whether to show password-related UI
# (the "Change password" section, the "Forgot password" link) -- Google-only
# accounts have password_hash = NULL and can't use either.
#
# trial_active: the 24-hour full-access window every new signup gets,
# gated purely by created_at -- no separate trial table, no cron job to
# expire it. It's just re-evaluated on every request, so it silently
# turns itself off once 24h have passed. Deliberately kept separate from
# `plan` (which stays exactly what Stripe's webhook says) so this can
# never interfere with real billing state -- the frontend is expected to
# treat access as unlocked when EITHER plan == 'pro' OR trial_active.
USER_FIELDS = """
    id, full_name, email, pending_email, created_at, plan, subscription_status,
    billing_interval, current_period_end, default_job_title, default_variants,
    default_posted_within_days, default_funding_filter, has_set_default_filters,
    (password_hash IS NOT NULL) AS has_password,
    (created_at + interval '24 hours' > now()) AS trial_active
"""


def _valid_full_name(full_name):
    return 2 <= len(full_name) <= 50 and bool(FULL_NAME_PATTERN.match(full_name))


def _sanitize_google_name(raw_name, email):
    """The full_name column only allows letters and single spaces (see
    schema.sql), but real names from Google can include hyphens, apostrophes,
    digits, or non-Latin scripts entirely. Strip down to what's allowed; if
    nothing usable survives (e.g. a name in a non-Latin script), fall back to
    the letters in the email's local part, then to a generic placeholder.
    The user can always edit this afterwards on their profile page.
    """
    cleaned = re.sub(r"[^A-Za-z ]", " ", raw_name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if _valid_full_name(cleaned):
        return cleaned

    local_part = re.sub(r"[^A-Za-z]", "", (email or "").split("@")[0])
    if _valid_full_name(local_part):
        return local_part

    return "Google User"


@bp.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    full_name = (body.get("full_name") or "").strip()
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not _valid_full_name(full_name):
        return jsonify(
            {"error": "Full name must be 2-50 characters: letters and spaces only"}
        ), 400
    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    cur = get_cursor()
    try:
        cur.execute(
            """
            INSERT INTO users (full_name, email, password_hash, is_verified)
            VALUES (%s, %s, %s, false)
            RETURNING id, full_name, email, created_at
            """,
            (full_name, email, generate_password_hash(password)),
        )
        user = cur.fetchone()
        cur.connection.commit()
    except psycopg2.errors.UniqueViolation:
        cur.connection.rollback()
        return jsonify({"error": "An account with that email already exists"}), 409

    token = issue_verification_token(user["id"])
    send_verification_email(user["email"], token, name=user["full_name"])

    return jsonify(
        {
            "message": "Account created. Check your email for a link to verify your address before logging in.",
            "user": {"id": user["id"], "full_name": user["full_name"], "email": user["email"]},
        }
    ), 201


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    cur = get_cursor()
    cur.execute(
        f"""
        SELECT {USER_FIELDS}, password_hash, is_verified
        FROM users WHERE email = %s
        """,
        (email,),
    )
    user = cur.fetchone()

    if user is None:
        return jsonify({"error": "Invalid email or password"}), 401

    if user["password_hash"] is None:
        return jsonify(
            {
                "error": "This account uses Google Sign-In. Use the \"Continue with Google\" button instead.",
                "code": "google_account",
            }
        ), 401

    if not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user["is_verified"]:
        return jsonify(
            {"error": "Please verify your email before logging in.", "code": "email_not_verified"}
        ), 403

    user.pop("password_hash")
    user.pop("is_verified")
    return jsonify({"token": issue_token(user["id"]), "user": user})


@bp.post("/google")
def google_login():
    """Log in (or sign up) via a Google ID token from the frontend's
    'Continue with Google' button. Three cases, in order:
      1. google_id already on file -> that's their account, log in.
      2. No google_id match, but a password account already exists with this
         email -> link Google to it (so they can use either from now on)
         and mark it verified (Google already verified the email).
      3. Neither -> brand-new account, created with no password.
    """
    body = request.get_json(silent=True) or {}
    credential = body.get("credential") or ""
    if not credential:
        return jsonify({"error": "Missing Google credential"}), 400

    client_id = current_app.config.get("GOOGLE_CLIENT_ID")
    if not client_id:
        return jsonify({"error": "Google sign-in isn't configured"}), 500

    try:
        payload = google_id_token.verify_oauth2_token(
            credential, google_requests.Request(), client_id
        )
    except ValueError:
        return jsonify({"error": "Invalid Google credential"}), 401

    if not payload.get("email_verified"):
        return jsonify({"error": "Google account email is not verified"}), 401

    google_id = payload["sub"]
    email = (payload.get("email") or "").strip().lower()
    full_name = _sanitize_google_name(payload.get("name"), email)

    cur = get_cursor()

    # 1. Already linked to this Google account.
    cur.execute(f"SELECT {USER_FIELDS} FROM users WHERE google_id = %s", (google_id,))
    user = cur.fetchone()

    if user is None:
        # 2. An existing password account with this email -> link it.
        cur.execute(
            f"""
            UPDATE users SET google_id = %s, is_verified = true
            WHERE email = %s AND google_id IS NULL
            RETURNING {USER_FIELDS}
            """,
            (google_id, email),
        )
        user = cur.fetchone()
        cur.connection.commit()

    if user is None:
        # 3. Brand-new account, no password.
        try:
            cur.execute(
                f"""
                INSERT INTO users (full_name, email, password_hash, google_id, is_verified)
                VALUES (%s, %s, NULL, %s, true)
                RETURNING {USER_FIELDS}
                """,
                (full_name, email, google_id),
            )
            user = cur.fetchone()
            cur.connection.commit()
        except psycopg2.errors.UniqueViolation:
            cur.connection.rollback()
            return jsonify({"error": "An account with that email already exists"}), 409

    return jsonify({"token": issue_token(user["id"]), "user": user})


@bp.get("/verify/<token>")
def verify_email(token):
    user_id = verify_verification_token(token)
    if user_id is None:
        return redirect(f"{current_app.config['FRONTEND_ORIGIN']}/login?verify_error=1")

    cur = get_cursor()
    cur.execute("UPDATE users SET is_verified = true WHERE id = %s", (user_id,))
    cur.connection.commit()

    return redirect(f"{current_app.config['FRONTEND_ORIGIN']}/login?verified=1")


@bp.post("/resend-verification")
def resend_verification():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    cur = get_cursor()
    cur.execute("SELECT id, full_name, email, is_verified FROM users WHERE email = %s", (email,))
    user = cur.fetchone()

    # Same response whether the account exists, is already verified, or the
    # email was typo'd — don't leak which emails have accounts.
    if user is not None and not user["is_verified"]:
        token = issue_verification_token(user["id"])
        send_verification_email(user["email"], token, name=user["full_name"])

    return jsonify({"message": "If that email has a pending account, a verification link has been sent."})


@bp.post("/forgot-password")
def forgot_password():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()

    cur = get_cursor()
    cur.execute("SELECT id, full_name, email FROM users WHERE email = %s", (email,))
    user = cur.fetchone()

    # Same response whether the account exists or the email was typo'd —
    # don't leak which emails have accounts.
    if user is not None:
        token = issue_password_reset_token(user["id"])
        send_password_reset_email(user["email"], token, name=user["full_name"])

    return jsonify({"message": "If that email has an account, a password reset link has been sent."})


@bp.post("/reset-password")
def reset_password():
    body = request.get_json(silent=True) or {}
    token = body.get("token") or ""
    password = body.get("password") or ""

    user_id = verify_password_reset_token(token)
    if user_id is None:
        return jsonify({"error": "This reset link is invalid or has expired."}), 400

    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    cur = get_cursor()
    cur.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (generate_password_hash(password), user_id),
    )
    cur.connection.commit()

    return jsonify({"message": "Password updated. You can now log in with your new password."})


@bp.get("/me")
@require_auth
def me():
    cur = get_cursor()
    cur.execute(f"SELECT {USER_FIELDS} FROM users WHERE id = %s", (g.user_id,))
    user = cur.fetchone()
    if user is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user)


@bp.put("/me")
@require_auth
def update_me():
    """Update the logged-in user's full name (profile page), and start an
    email change if the submitted email differs from their current one.

    The email doesn't change immediately: the new address is stashed in
    pending_email and a confirmation link is emailed to it. The `email`
    column itself only updates once that link is clicked (see
    confirm_email below) -- this proves the user actually controls the new
    inbox before things like login and password-reset start using it.
    """
    body = request.get_json(silent=True) or {}
    full_name = (body.get("full_name") or "").strip()
    email = (body.get("email") or "").strip().lower()

    if not _valid_full_name(full_name):
        return jsonify(
            {"error": "Full name must be 2-50 characters: letters and spaces only"}
        ), 400
    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required"}), 400

    cur = get_cursor()
    cur.execute("SELECT email FROM users WHERE id = %s", (g.user_id,))
    current = cur.fetchone()
    if current is None:
        return jsonify({"error": "User not found"}), 404

    if email == current["email"]:
        # No real email change -- and if they typed their current address
        # back in, that reads as "never mind", so drop any pending change too.
        cur.execute(
            f"""
            UPDATE users SET full_name = %s, pending_email = NULL
            WHERE id = %s
            RETURNING {USER_FIELDS}
            """,
            (full_name, g.user_id),
        )
        updated = cur.fetchone()
        cur.connection.commit()
        return jsonify(updated)

    # Changing email: `email` itself isn't touched here, so a UniqueViolation
    # can't catch a collision the way the no-op branch above's UPDATE would --
    # check explicitly instead.
    cur.execute("SELECT 1 FROM users WHERE email = %s AND id != %s", (email, g.user_id))
    if cur.fetchone() is not None:
        return jsonify({"error": "An account with that email already exists"}), 409

    cur.execute(
        f"""
        UPDATE users SET full_name = %s, pending_email = %s
        WHERE id = %s
        RETURNING {USER_FIELDS}
        """,
        (full_name, email, g.user_id),
    )
    updated = cur.fetchone()
    cur.connection.commit()

    token = issue_email_change_token(g.user_id, email)
    send_email_change_confirmation(email, token, name=full_name)

    return jsonify(updated)


@bp.get("/confirm-email/<token>")
def confirm_email(token):
    """Landed on by clicking the link sent to a NEW email address after a
    profile-page email change. Only swaps `email` over if pending_email on
    the account still matches what this specific token was issued for --
    guards against a stale link after the user cancelled or re-requested
    the change with a different address."""
    data = verify_email_change_token(token)
    if data is None:
        return redirect(f"{current_app.config['FRONTEND_ORIGIN']}/profile?email_change_error=invalid")

    user_id, new_email = data.get("user_id"), data.get("new_email")

    cur = get_cursor()
    cur.execute("SELECT pending_email FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    if row is None or row["pending_email"] != new_email:
        return redirect(f"{current_app.config['FRONTEND_ORIGIN']}/profile?email_change_error=stale")

    try:
        cur.execute(
            "UPDATE users SET email = %s, pending_email = NULL WHERE id = %s",
            (new_email, user_id),
        )
        cur.connection.commit()
    except psycopg2.errors.UniqueViolation:
        # Someone else grabbed this email while the link sat unclicked.
        cur.connection.rollback()
        return redirect(f"{current_app.config['FRONTEND_ORIGIN']}/profile?email_change_error=taken")

    return redirect(f"{current_app.config['FRONTEND_ORIGIN']}/profile?email_changed=1")


@bp.post("/me/cancel-email-change")
@require_auth
def cancel_email_change():
    """Lets the user back out of a pending email change from the profile page."""
    cur = get_cursor()
    cur.execute(
        f"""
        UPDATE users SET pending_email = NULL
        WHERE id = %s
        RETURNING {USER_FIELDS}
        """,
        (g.user_id,),
    )
    updated = cur.fetchone()
    cur.connection.commit()
    if updated is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify(updated)


@bp.put("/me/password")
@require_auth
def update_password():
    """Change the logged-in user's password (requires the current password)."""
    body = request.get_json(silent=True) or {}
    current_password = body.get("current_password") or ""
    new_password = body.get("new_password") or ""

    if len(new_password) < 8:
        return jsonify({"error": "New password must be at least 8 characters"}), 400

    cur = get_cursor()
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (g.user_id,))
    user = cur.fetchone()
    if user is None:
        return jsonify({"error": "User not found"}), 404
    if user["password_hash"] is None:
        return jsonify(
            {"error": "This account uses Google Sign-In and doesn't have a password to change."}
        ), 400
    if not check_password_hash(user["password_hash"], current_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    cur.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (generate_password_hash(new_password), g.user_id),
    )
    cur.connection.commit()

    return jsonify({"message": "Password updated."})