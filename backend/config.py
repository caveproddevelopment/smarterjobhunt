import os

from dotenv import load_dotenv

load_dotenv()


def _parse_origins(value, fallback):
    """Comma-separated list of allowed frontend origins, e.g.
    'https://thesmarterjobhunt.com,https://www.thesmarterjobhunt.com'.
    Falls back to a single-origin list if the env var isn't set."""
    if not value:
        return [fallback]
    return [origin.strip() for origin in value.split(",") if origin.strip()]


class Config:
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql://smarterjobhunt:devpassword@localhost:5432/smarterjobhunt"
    )
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")

    # Canonical frontend origin — used to build links (email verification
    # redirect, password reset link). Should be the one domain you want
    # those emailed links to point to (your new custom domain).
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173")

    # All origins allowed to call the API (CORS). Comma-separated in the
    # env var, e.g.:
    #   FRONTEND_ORIGINS=https://thesmarterjobhunt.com,https://www.thesmarterjobhunt.com,https://smarterjobhunt.vercel.app
    # Falls back to FRONTEND_ORIGIN alone if FRONTEND_ORIGINS isn't set, so
    # this is backward compatible with the old single-origin setup.
    FRONTEND_ORIGINS = _parse_origins(
        os.environ.get("FRONTEND_ORIGINS"),
        os.environ.get("FRONTEND_ORIGIN", "http://localhost:5173"),
    )

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

    # Stripe billing. Weekly/monthly are separate Stripe Price objects — create
    # both (same Product, two recurring prices) in the Stripe Dashboard and
    # drop their IDs in here. STRIPE_WEBHOOK_SECRET comes from the webhook
    # endpoint's "Signing secret" once you register it (or from `stripe
    # listen` while testing locally).
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")
    STRIPE_PRICE_WEEKLY = os.environ.get("STRIPE_PRICE_WEEKLY")
    STRIPE_PRICE_MONTHLY = os.environ.get("STRIPE_PRICE_MONTHLY")

    # Claude-powered title-variant agent (title_variant_agent.py, called from
    # routes/title_variants.py on a job_title_variants cache miss). Required
    # for that endpoint to work -- if unset, it returns a 502 rather than
    # falling back to anything jobs-table-dependent.
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")