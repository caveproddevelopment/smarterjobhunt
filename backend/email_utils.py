"""
Email sending — currently just the account-verification email.

Uses plain smtplib against whatever SMTP_HOST/PORT/USERNAME/PASSWORD is
configured (works with SendGrid, Mailgun, Postmark, AWS SES's SMTP
interface, Gmail app passwords, etc — anything that speaks SMTP). If
SMTP_HOST isn't set (e.g. local dev without real credentials), the
email is logged to the console instead of sent, so registration still
works end-to-end without crashing.
"""

import smtplib
from email.message import EmailMessage

from flask import current_app


def _verification_url(token: str) -> str:
    return f"{current_app.config['BACKEND_ORIGIN']}/api/auth/verify/{token}"


def send_verification_email(to_email: str, token: str) -> None:
    verify_url = _verification_url(token)

    subject = "Verify your SmarterJobHunt account"
    body = (
        "Welcome to SmarterJobHunt!\n\n"
        "Click the link below to verify your email address and activate your account:\n\n"
        f"{verify_url}\n\n"
        "This link expires in 24 hours. If you didn't create this account, you can ignore this email."
    )

    smtp_host = current_app.config.get("SMTP_HOST")
    if not smtp_host:
        # No SMTP configured — log instead of sending, so local dev / early
        # testing doesn't need real email credentials to register a user.
        current_app.logger.warning(
            "SMTP_HOST not set — skipping real send. Verification link for %s: %s",
            to_email,
            verify_url,
        )
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = current_app.config["MAIL_FROM"]
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, current_app.config["SMTP_PORT"]) as server:
        server.starttls()
        username = current_app.config.get("SMTP_USERNAME")
        password = current_app.config.get("SMTP_PASSWORD")
        if username and password:
            server.login(username, password)
        server.send_message(msg)
