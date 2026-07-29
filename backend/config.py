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
        os.environ.get("EMAIL_VERIFICATION_MAX_AGE_SECONDS", 60 * 5)  # 5 min
    )

    # Password reset
    PASSWORD_RESET_MAX_AGE_SECONDS = int(
        os.environ.get("PASSWORD_RESET_MAX_AGE_SECONDS", 60 * 5)  # 5 min
    )

    # Google Apps Script web app (Gmail-backed) that sends verification/reset
    # emails. There's no shared secret — access is controlled purely by
    # keeping this URL private, so treat it like a credential.
    APPS_SCRIPT_URL = os.environ.get("APPS_SCRIPT_URL")
