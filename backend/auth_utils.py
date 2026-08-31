from functools import wraps
import secrets

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarterjobhunt-auth")


def _verification_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarterjobhunt-email-verify")


def _password_reset_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarterjobhunt-password-reset")


def _email_change_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarterjobhunt-email-change")


def issue_token(user_id):
    return _serializer().dumps({"user_id": user_id})


def issue_verification_token(user_id):
    return _verification_serializer().dumps({"user_id": user_id})


def issue_password_reset_token(user_id):
    return _password_reset_serializer().dumps({"user_id": user_id})


def issue_email_change_token(user_id, new_email):
    """Encodes both the user and the requested new address, so confirming
    the link can't be tricked into applying a *different* pending change
    than the one this particular email was sent for (see confirm_email)."""
    return _email_change_serializer().dumps({"user_id": user_id, "new_email": new_email})


def verify_verification_token(token):
    """Return the user_id encoded in an email-verification token, or None if
    it's missing/invalid/expired."""
    try:
        data = _verification_serializer().loads(
            token, max_age=current_app.config["EMAIL_VERIFICATION_MAX_AGE_SECONDS"]
        )
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def verify_password_reset_token(token):
    """Return the user_id encoded in a password-reset token, or None if
    it's missing/invalid/expired.

    Note: like the verification token, this is a stateless signed token —
    it stays valid for anyone who has it until PASSWORD_RESET_MAX_AGE_SECONDS
    elapses, even after one use. Fine for a 5-minute window; if that ever
    matters, add a `used` flag to a small DB table keyed by token.
    """
    try:
        data = _password_reset_serializer().loads(
            token, max_age=current_app.config["PASSWORD_RESET_MAX_AGE_SECONDS"]
        )
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def verify_email_change_token(token):
    """Return {"user_id": ..., "new_email": ...} encoded in an email-change
    token, or None if it's missing/invalid/expired."""
    try:
        return _email_change_serializer().loads(
            token, max_age=current_app.config["EMAIL_CHANGE_MAX_AGE_SECONDS"]
        )
    except (BadSignature, SignatureExpired):
        return None


def verify_token(token):
    """Return the user_id encoded in the token, or None if it's missing/invalid/expired."""
    try:
        data = _serializer().loads(token, max_age=current_app.config["TOKEN_MAX_AGE_SECONDS"])
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


def require_auth(view):
    """Decorator: reject the request unless a valid 'Authorization: Bearer <token>' header
    is present, and set g.user_id for the view to use."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed Authorization header"}), 401

        user_id = verify_token(header.removeprefix("Bearer ").strip())
        if user_id is None:
            return jsonify({"error": "Invalid or expired token"}), 401

        g.user_id = user_id
        return view(*args, **kwargs)

    return wrapped


def optional_auth(view):
    """Like require_auth, but lets the request through with g.user_id = None when no
    (valid) token is present — for endpoints that work for logged-out browsing too."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        g.user_id = None
        if header.startswith("Bearer "):
            g.user_id = verify_token(header.removeprefix("Bearer ").strip())
        return view(*args, **kwargs)

    return wrapped


def require_admin_key(view):
    """Decorator: reject the request unless it carries the shared admin
    secret in an 'X-Admin-Key' header. Gates the staging-review endpoints
    (routes/staging.py) -- there's no per-user admin role in the users
    table, just this one shared secret (ADMIN_API_KEY in config.py)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        expected = current_app.config.get("ADMIN_API_KEY")
        if not expected:
            return jsonify({"error": "Admin endpoints aren't configured"}), 500

        provided = request.headers.get("X-Admin-Key", "")
        if not secrets.compare_digest(provided, expected):
            return jsonify({"error": "Invalid admin key"}), 401

        return view(*args, **kwargs)

    return wrapped