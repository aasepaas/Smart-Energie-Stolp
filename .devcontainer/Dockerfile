# Werkcontainer: Python 3.12 als basis, Node 22 komt via de feature in devcontainer.json.
FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# psql voor de database, libgomp1 voor XGBoost en LightGBM (PyCaret).
# De yarn-bron uit de basisimage heeft een verlopen sleutel en is niet nodig.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client libgomp1 \
    && rm -rf /var/lib/apt/lists/*
