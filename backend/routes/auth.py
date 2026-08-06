import re

import psycopg2
from flask import Blueprint, current_app, g, jsonify, redirect, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import (
    issue_password_reset_token,
    issue_token,
    issue_verification_token,
    require_auth,
    verify_password_reset_token,
    verify_verification_token,
)
from db.connection import get_cursor
from email_utils import send_password_reset_email, send_verification_email

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# Letters and single spaces between words (e.g. "John Smith"). No leading/
# trailing space, no double spaces, no digits or punctuation.
FULL_NAME_PATTERN = re.compile(r"^[A-Za-z]+( [A-Za-z]+)*$")


def _valid_full_name(full_name):
    return 2 <= len(full_name) <= 50 and bool(FULL_NAME_PATTERN.match(full_name))


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
        """
        SELECT id, full_name, email, password_hash, is_verified, plan,
               subscription_status, billing_interval, current_period_end,
               default_job_title, default_variants, default_posted_within_days,
               default_funding_filter, has_set_default_filters
        FROM users WHERE email = %s
        """,
        (email,),
    )
    user = cur.fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid email or password"}), 401

    if not user["is_verified"]:
        return jsonify(
            {"error": "Please verify your email before logging in.", "code": "email_not_verified"}
        ), 403

    return jsonify(
        {
            "token": issue_token(user["id"]),
            "user": {
                "id": user["id"],
                "full_name": user["full_name"],
                "email": user["email"],
                "plan": user["plan"],
                "subscription_status": user["subscription_status"],
                "billing_interval": user["billing_interval"],
                "current_period_end": user["current_period_end"],
                "default_job_title": user["default_job_title"],
                "default_variants": user["default_variants"],
                "default_posted_within_days": user["default_posted_within_days"],
                "default_funding_filter": user["default_funding_filter"],
                "has_set_default_filters": user["has_set_default_filters"],
            },
        }
    )


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
    cur.execute(
        """
        SELECT id, full_name, email, created_at, plan,
               subscription_status, billing_interval, current_period_end,
               default_job_title, default_variants, default_posted_within_days,
               default_funding_filter, has_set_default_filters
        FROM users WHERE id = %s
        """,
        (g.user_id,),
    )
    user = cur.fetchone()
    if user is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user)


@bp.put("/me")
@require_auth
def update_me():
    """Update the logged-in user's full name and/or email (profile page)."""
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
    try:
        cur.execute(
            """
            UPDATE users
            SET full_name = %s, email = %s
            WHERE id = %s
            RETURNING id, full_name, email, created_at, plan,
                      subscription_status, billing_interval, current_period_end,
                      default_job_title, default_variants, default_posted_within_days,
                      default_funding_filter, has_set_default_filters
            """,
            (full_name, email, g.user_id),
        )
        updated = cur.fetchone()
        cur.connection.commit()
    except psycopg2.errors.UniqueViolation:
        cur.connection.rollback()
        return jsonify({"error": "An account with that email already exists"}), 409

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
    if user is None or not check_password_hash(user["password_hash"], current_password):
        return jsonify({"error": "Current password is incorrect"}), 401

    cur.execute(
        "UPDATE users SET password_hash = %s WHERE id = %s",
        (generate_password_hash(new_password), g.user_id),
    )
    cur.connection.commit()

    return jsonify({"message": "Password updated."})
