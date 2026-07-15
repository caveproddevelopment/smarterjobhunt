from functools import wraps

from flask import current_app, g, jsonify, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


def _serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarterjobhunt-auth")


def _verification_serializer():
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="smarterjobhunt-email-verify")


def issue_token(user_id):
    return _serializer().dumps({"user_id": user_id})


def issue_verification_token(user_id):
    return _verification_serializer().dumps({"user_id": user_id})


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
