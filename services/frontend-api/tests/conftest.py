import os

# Test values; set before frontend_api.config is imported
os.environ.setdefault("SES_JWT_SECRET", "test-secret-of-at-least-thirty-two-characters")
os.environ.setdefault("REFRESH_COOKIE_SECURE", "false")
os.environ.setdefault("SES_TOKEN_FRONTEND", "test-frontend")
