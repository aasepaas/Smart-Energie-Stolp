import os

# Service token of the Frontend API; set before data_processing_service.config is imported
os.environ.setdefault("SES_TOKEN_FRONTEND", "test-frontend")
