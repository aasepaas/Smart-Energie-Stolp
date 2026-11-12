"""Backend client (component 'Backend client' in C4 3.3): de enige weg naar de Backend API.

Volgt de Backend API op main (services/backend-api, alles onder /v1):

    list_meters      GET   /meters
    add_meters       POST  /meters          {"meter_references": [...]}
    upsert_readings  PUT   /readings        [{meter_reference, ts, to_grid_kwh, from_grid_kwh}]
    start_import     POST  /imports         {file_name, file_hash, period_start, period_end}
    update_import    PATCH /imports/{id}    {status, period_start, period_end, row_count, ...}
    list_readings    GET   /readings?start&end            all meters in [start, end)
    replace_simultaneity  PUT /simultaneity  {start, end, rows}  replaces [start, end)

Adres en token komen uit BACKEND_API_URL en SES_TOKEN_PROCESSING (gezet in compose.yaml).
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import httpx

from . import config


class BackendError(Exception):
    """De Backend API is niet bereikbaar of weigert het verzoek."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class DuplicateImportError(BackendError):
    """Dit bestand (zelfde SHA-256) is al eerder geimporteerd (409)."""


class BackendClient:
    def __init__(self, base_url: str | None = None, token: str | None = None,
                 http: httpx.Client | None = None):
        if http is None:
            base_url = base_url or os.environ.get("BACKEND_API_URL", "")
            token = token or os.environ.get("SES_TOKEN_PROCESSING", "")
            if not base_url or not token:
                raise BackendError("BACKEND_API_URL en SES_TOKEN_PROCESSING moeten gezet zijn")
            http = httpx.Client(base_url=base_url, timeout=config.BACKEND_TIMEOUT,
                                headers={"Authorization": f"Bearer {token}"})
        self._http = http

    def list_meters(self) -> list[str]:
        return [m["meter_reference"] for m in self._request("GET", "/meters")]

    def add_meters(self, meter_references: list[str]) -> int:
        added = 0
        for start in range(0, len(meter_references), config.MAX_BATCH):
            batch = meter_references[start:start + config.MAX_BATCH]
            added += self._request("POST", "/meters", json={"meter_references": batch})["count"]
        return added

    def upsert_readings(self, rows: list[dict[str, Any]]) -> int:
        return self._request("PUT", "/readings", json=rows)["count"]

    def start_import(self, file_name: str, file_hash: str) -> str:
        try:
            body = {"file_name": file_name, "file_hash": file_hash}
            return self._request("POST", "/imports", json=body)["id"]
        except BackendError as exc:
            if exc.status_code == 409:
                raise DuplicateImportError("dit bestand is al eerder geimporteerd", 409) from exc
            raise

    def update_import(self, import_id: str, **fields: Any) -> None:
        body = {k: v.isoformat() if isinstance(v, datetime) else v for k, v in fields.items()}
        self._request("PATCH", f"/imports/{import_id}", json=body)

    def list_readings(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        params = {"start": start.isoformat(), "end": end.isoformat()}
        return self._request("GET", "/readings", params=params)

    def replace_simultaneity(self, start: datetime, end: datetime,
                             rows: list[dict[str, Any]]) -> int:
        body = {"start": start.isoformat(), "end": end.isoformat(), "rows": rows}
        return self._request("PUT", "/simultaneity", json=body)["count"]

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise BackendError(f"Backend API niet bereikbaar ({self._http.base_url}): {exc}") from exc
        if response.is_error:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise BackendError(f"Backend API {method} {path} gaf {response.status_code}: {detail}",
                               response.status_code)
        return response.json()


def create_backend() -> BackendClient:
    """Eén client per import; adres en token uit de omgeving."""
    return BackendClient()
