import psycopg2
from flask import Blueprint, current_app, g, jsonify, redirect, request
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import (
    issue_token,
    issue_verification_token,
    require_auth,
    verify_verification_token,
)
from db.connection import get_cursor
from email_utils import send_verification_email

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.post("/register")
def register():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    if not email or "@" not in email:
        return jsonify({"error": "A valid email is required"}), 400
    if len(password) < 8:
        return jsonify({"error": "Password must be at least 8 characters"}), 400

    cur = get_cursor()
    try:
        cur.execute(
            """
            INSERT INTO users (email, password_hash, is_verified)
            VALUES (%s, %s, false)
            RETURNING id, email, created_at
            """,
            (email, generate_password_hash(password)),
        )
        user = cur.fetchone()
        cur.connection.commit()
    except psycopg2.errors.UniqueViolation:
        cur.connection.rollback()
        return jsonify({"error": "An account with that email already exists"}), 409

    token = issue_verification_token(user["id"])
    send_verification_email(user["email"], token)

    return jsonify(
        {
            "message": "Account created. Check your email for a link to verify your address before logging in.",
            "user": {"id": user["id"], "email": user["email"]},
        }
    ), 201


@bp.post("/login")
def login():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip().lower()
    password = body.get("password") or ""

    cur = get_cursor()
    cur.execute(
        "SELECT id, email, password_hash, is_verified FROM users WHERE email = %s",
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
        {"token": issue_token(user["id"]), "user": {"id": user["id"], "email": user["email"]}}
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
    cur.execute("SELECT id, email, is_verified FROM users WHERE email = %s", (email,))
    user = cur.fetchone()

    # Same response whether the account exists, is already verified, or the
    # email was typo'd — don't leak which emails have accounts.
    if user is not None and not user["is_verified"]:
        token = issue_verification_token(user["id"])
        send_verification_email(user["email"], token)

    return jsonify({"message": "If that email has a pending account, a verification link has been sent."})


@bp.get("/me")
@require_auth
def me():
    cur = get_cursor()
    cur.execute("SELECT id, email, created_at FROM users WHERE id = %s", (g.user_id,))
    user = cur.fetchone()
    if user is None:
        return jsonify({"error": "User not found"}), 404
    return jsonify(user)
