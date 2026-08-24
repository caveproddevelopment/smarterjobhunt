"""
Email sending — verification and password reset emails, sent through a
Google Apps Script web app (Gmail-backed) instead of SMTP.

There's no shared secret in the request payload; access is controlled
purely by keeping APPS_SCRIPT_URL private, so treat it like a credential
(don't commit it, don't log it).

If APPS_SCRIPT_URL isn't set (e.g. local dev without a deployment), the
email is logged to the console instead of sent, so registration and
password-reset still work end-to-end without needing Apps Script deployed.
"""

import requests
from flask import current_app


def _verification_url(token: str) -> str:
    return f"{current_app.config['BACKEND_ORIGIN']}/api/auth/verify/{token}"


def _password_reset_url(token: str) -> str:
    return f"{current_app.config['FRONTEND_ORIGIN']}/reset-password?token={token}"


def _email_change_url(token: str) -> str:
    return f"{current_app.config['BACKEND_ORIGIN']}/api/auth/confirm-email/{token}"


def _send_via_apps_script(payload: dict, fallback_link: str) -> bool:
    """Returns True if the send is believed to have succeeded, False
    otherwise (Apps Script not configured, unreachable, or it reported
    failure). Callers that already persist their own record of the thing
    being emailed (e.g. contact_messages) can use this to mark it as sent."""
    apps_script_url = current_app.config.get("APPS_SCRIPT_URL")

    if not apps_script_url:
        current_app.logger.warning(
            "APPS_SCRIPT_URL not set — skipping real send. %s link for %s: %s",
            payload["type"],
            payload["email"],
            fallback_link,
        )
        return False

    try:
        resp = requests.post(apps_script_url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("success"):
            current_app.logger.error(
                "Apps Script reported failure sending %s email to %s: %s",
                payload["type"], payload["email"], result.get("error"),
            )
            return False
        return True
    except requests.RequestException:
        current_app.logger.exception(
            "Failed to reach Apps Script while sending %s email to %s",
            payload["type"], payload["email"],
        )
        return False


def send_verification_email(to_email: str, token: str, name: str | None = None) -> None:
    link = _verification_url(token)
    _send_via_apps_script(
        {"type": "verification", "email": to_email, "link": link, "name": name},
        fallback_link=link,
    )


def send_password_reset_email(to_email: str, token: str, name: str | None = None) -> None:
    link = _password_reset_url(token)
    _send_via_apps_script(
        {"type": "reset", "email": to_email, "link": link, "name": name},
        fallback_link=link,
    )


def send_email_change_confirmation(to_email: str, token: str, name: str | None = None) -> None:
    """Sent to the NEW address the user entered on their profile page --
    proves they actually control that inbox before /me's email column
    changes over to it (see confirm_email in routes/auth.py)."""
    link = _email_change_url(token)
    _send_via_apps_script(
        {"type": "email_change", "email": to_email, "link": link, "name": name},
        fallback_link=link,
    )


def send_contact_email(sender_name: str, sender_email: str, subject: str, message: str) -> bool:
    """Notifies CONTACT_TO_EMAIL about a new "Contact us" form submission
    (routes/contact.py). Returns True/False so the route can record whether
    the notification actually went out -- the submission itself is already
    committed to contact_messages before this is called, so a False here
    just means "no email fired", not "message lost"."""
    to_email = current_app.config.get("CONTACT_TO_EMAIL")

    if not to_email:
        current_app.logger.warning(
            "CONTACT_TO_EMAIL not set — skipping notification for message from %s <%s>",
            sender_name, sender_email,
        )
        return False

    return _send_via_apps_script(
        {
            "type": "contact",
            "email": to_email,
            "sender_name": sender_name,
            "sender_email": sender_email,
            "subject": subject,
            "message": message,
        },
        fallback_link=f"{sender_name} <{sender_email}>: {subject}",
    )