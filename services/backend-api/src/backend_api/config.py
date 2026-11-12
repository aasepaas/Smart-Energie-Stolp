"""Settings for the backend api from the envoirement variables."""

import os

# logging in to the database as ses_backend; with each request it changes the role to svc_processing,
# svc_training or svc_forecast (see db.py).
DATABASE_URL = os.environ.get(
    "BACKEND_DATABASE_URL", "postgresql://ses_backend:user@db:5432/ses"
)

# secret token for each service
SERVICE_TOKENS = {
    "processing": os.environ.get("SES_TOKEN_PROCESSING", ""),
    "training": os.environ.get("SES_TOKEN_TRAINING", ""),
    "forecast": os.environ.get("SES_TOKEN_FORECAST", ""),
}

# max rows for reqeusts; big requests should be sent in multiple little requests
MAX_BATCH = 10_000
