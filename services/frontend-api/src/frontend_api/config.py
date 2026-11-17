"""Settings of the Frontend API, all from environment variables."""

import os


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes"}


# Logs in to the database as ses_frontend; every request switches to web_participant
# or web_admin (see query_executor.py).
DATABASE_URL = os.environ.get(
    "FRONTEND_DATABASE_URL", "postgresql://ses_frontend:user@db:5432/ses"
)

# Secret used to sign the JWTs (HS256). Required, at least 32 characters.
JWT_SECRET = os.environ.get("SES_JWT_SECRET", "")
JWT_ISSUER = "ses-frontend-api"
ACCESS_TOKEN_MINUTES = int(os.environ.get("ACCESS_TOKEN_MINUTES", "15"))
REFRESH_TOKEN_HOURS = int(os.environ.get("REFRESH_TOKEN_HOURS", "168"))

# The refresh token lives in an HttpOnly cookie. Secure should only be off for local http.
REFRESH_COOKIE_NAME = "ses_refresh"
REFRESH_COOKIE_PATH = "/v1/auth"
REFRESH_COOKIE_SECURE = _bool("REFRESH_COOKIE_SECURE", True)

# Origins of the web app that may call the API from a browser (comma separated).
# Empty when the web app is served from the same origin (behind one reverse proxy).
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]

# Data processing service (receives the CSV uploads)
PROCESSING_SERVICE_URL = os.environ.get(
    "PROCESSING_SERVICE_URL", "http://data-processing-service:8000"
)
PROCESSING_TIMEOUT = float(os.environ.get("PROCESSING_TIMEOUT", "300"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(200 * 1024 * 1024)))

# Longest period one data request may cover
MAX_PERIOD_DAYS = int(os.environ.get("MAX_PERIOD_DAYS", "366"))

# Time zone for day and month buckets, so a day runs from local midnight to midnight
TIMEZONE = os.environ.get("SES_TIMEZONE", "Europe/Amsterdam")

MIN_PASSWORD_LENGTH = 12
