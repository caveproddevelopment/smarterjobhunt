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


def _send_via_apps_script(payload: dict, fallback_link: str) -> None:
    apps_script_url = current_app.config.get("APPS_SCRIPT_URL")

    if not apps_script_url:
        current_app.logger.warning(
            "APPS_SCRIPT_URL not set — skipping real send. %s link for %s: %s",
            payload["type"],
            payload["email"],
            fallback_link,
        )
        return

    try:
        resp = requests.post(apps_script_url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if not result.get("success"):
            current_app.logger.error(
                "Apps Script reported failure sending %s email to %s: %s",
                payload["type"], payload["email"], result.get("error"),
            )
    except requests.RequestException:
        current_app.logger.exception(
            "Failed to reach Apps Script while sending %s email to %s",
            payload["type"], payload["email"],
        )


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
