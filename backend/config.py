import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql://smarterjobhunt:devpassword@localhost:5432/smarterjobhunt"
    )
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")
    BACKEND_ORIGIN = os.environ.get("BACKEND_ORIGIN", "http://localhost:5000")
    TOKEN_MAX_AGE_SECONDS = int(os.environ.get("TOKEN_MAX_AGE_SECONDS", 60 * 60 * 24 * 14))

    # Email verification
    EMAIL_VERIFICATION_MAX_AGE_SECONDS = int(
        os.environ.get("EMAIL_VERIFICATION_MAX_AGE_SECONDS", 60 * 60 * 24)  # 24h
    )
    SMTP_HOST = os.environ.get("SMTP_HOST")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
    MAIL_FROM = os.environ.get("MAIL_FROM", "SmarterJobHunt <no-reply@smarterjobhunt.com>")
