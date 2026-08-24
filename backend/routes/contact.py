import re

from flask import Blueprint, jsonify, request

from db.connection import get_cursor
from email_utils import send_contact_email

bp = Blueprint("contact", __name__, url_prefix="/api/contact")

VALID_SUBJECTS = {"general", "bug", "feedback", "account", "business", "other"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MAX_NAME_LEN = 200
MAX_EMAIL_LEN = 320
MAX_MESSAGE_LEN = 5000


@bp.post("")
def submit_contact():
    body = request.get_json(silent=True) or {}

    # Honeypot: "website" isn't a real field on the form and is hidden
    # off-screen (see AboutUs.jsx) -- humans never fill it, simple bots
    # that blindly fill every input do. Pretend success so nothing about
    # the check leaks back, but skip the DB write and the email.
    if (body.get("website") or "").strip():
        return jsonify({"ok": True}), 201

    name = (body.get("name") or "").strip()
    email = (body.get("email") or "").strip()
    subject = (body.get("subject") or "").strip()
    message = (body.get("message") or "").strip()

    if not name or not email or not subject or not message:
        return jsonify({"error": "name, email, subject, and message are all required"}), 400

    if subject not in VALID_SUBJECTS:
        return jsonify({"error": f"subject must be one of {sorted(VALID_SUBJECTS)}"}), 400

    if not EMAIL_RE.match(email):
        return jsonify({"error": "that doesn't look like a valid email address"}), 400

    if len(name) > MAX_NAME_LEN:
        return jsonify({"error": f"name must be {MAX_NAME_LEN} characters or fewer"}), 400

    if len(email) > MAX_EMAIL_LEN:
        return jsonify({"error": f"email must be {MAX_EMAIL_LEN} characters or fewer"}), 400

    if len(message) > MAX_MESSAGE_LEN:
        return jsonify({"error": f"message must be {MAX_MESSAGE_LEN} characters or fewer"}), 400

    cur = get_cursor()
    cur.execute(
        """
        INSERT INTO contact_messages (name, email, subject, message)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (name, email, subject, message),
    )
    message_id = cur.fetchone()["id"]
    cur.connection.commit()

    # The submission is already durably saved above -- a failed/unconfigured
    # notification send here doesn't affect the response to the user.
    if send_contact_email(name, email, subject, message):
        cur.execute("UPDATE contact_messages SET emailed = true WHERE id = %s", (message_id,))
        cur.connection.commit()

    return jsonify({"ok": True}), 201
