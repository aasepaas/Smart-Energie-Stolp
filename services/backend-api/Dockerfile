FROM python:3.12-slim

WORKDIR /app

# Eerst alleen pyproject.toml, zodat de dependencies in de cache blijven
COPY pyproject.toml ./
COPY src ./src
# Editable: in de dev-omgeving wordt src/ over deze map gemount, zodat
# wijzigingen direct zichtbaar zijn (uvicorn --reload)
RUN pip install --no-cache-dir -e .

# Niet als root draaien
RUN useradd --create-home api
USER api

EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health')"

CMD ["uvicorn", "backend_api.main:app", "--host", "0.0.0.0", "--port", "8001"]
