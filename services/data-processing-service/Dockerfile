FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
# Editable: in the dev environment src/ is mounted over this folder,
# so changes are picked up immediately (uvicorn --reload)
RUN pip install --no-cache-dir -e .

# Do not run as root
RUN useradd --create-home api
USER api

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "data_processing_service.import_endpoint:app", "--host", "0.0.0.0", "--port", "8000"]
