"""Backend client (component 'Backend client' in C4 3.3): de enige weg naar de Backend API.

De Backend API bestaat nog niet op main. Daarom staat hier:
- `BackendClient`: de interface die de rest van de service gebruikt. De methodes volgen het
  contract op branch ses-214-backend_api (alles onder /v1):
      list_meters      GET   /meters
      add_meters       POST  /meters          {"meter_references": [...]}
      upsert_readings  PUT   /readings        [{meter_reference, ts, to_grid_kwh, from_grid_kwh}]
      start_import     POST  /imports         {file_name, file_hash, period_start, period_end} (409 = al geimporteerd)
      update_import    PATCH /imports/{id}    {status, period_start, period_end, row_count, new_meter_count, error_message}
- `DryRunBackendClient`: schrijft precies die verzoeken als JSON naar een map, zodat je kunt
  zien wat er naar de Backend API zou gaan. Een HTTP-client (httpx) komt hier later naast,
  met dezelfde methodes; de rest van de service hoeft dan niet te veranderen.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from . import config


class DuplicateImportError(Exception):
    """Dit bestand (zelfde SHA-256) is al eerder geimporteerd (Backend API: 409)."""

    def __init__(self, file_hash: str, existing_id: str | None = None):
        super().__init__(f"bestand met hash {file_hash[:12]}... is al geimporteerd")
        self.existing_id = existing_id


class BackendClient(Protocol):
    def list_meters(self) -> list[str]: ...

    def add_meters(self, meter_references: list[str]) -> int: ...

    def upsert_readings(self, rows: list[dict[str, Any]]) -> int: ...

    def start_import(self, file_name: str, file_hash: str,
                     period_start: datetime | None = None,
                     period_end: datetime | None = None) -> str: ...

    def update_import(self, import_id: str, **fields: Any) -> None: ...


class DryRunBackendClient:
    """Schrijft alle verzoeken naar `directory` in plaats van naar de Backend API.

    directory/state.json          bekende meters en imports (voor nieuwe meters en 409)
    directory/<import_id>/        per import de verzoeken in volgorde:
        01_post_imports.json, 02_post_meters.json, 03_put_readings_0001.json, ...,
        99_patch_imports.json en report.json (door de orchestrator)
    """

    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._state_file = self.directory / "state.json"
        self._current: str | None = None
        self._batch = 0

    # --- Interface ------------------------------------------------------------------
    def list_meters(self) -> list[str]:
        return sorted(self._state()["meters"])

    def add_meters(self, meter_references: list[str]) -> int:
        state = self._state()
        new = [m for m in meter_references if m not in state["meters"]]
        state["meters"] = sorted(set(state["meters"]) | set(new))
        self._save_state(state)
        self._write("02_post_meters.json", {"meter_references": meter_references})
        return len(new)

    def upsert_readings(self, rows: list[dict[str, Any]]) -> int:
        if len(rows) > config.MAX_BATCH:
            raise ValueError(f"maximaal {config.MAX_BATCH} rijen per verzoek")
        self._batch += 1
        self._write(f"03_put_readings_{self._batch:04d}.json", rows)
        return len(rows)

    def start_import(self, file_name: str, file_hash: str,
                     period_start: datetime | None = None,
                     period_end: datetime | None = None) -> str:
        state = self._state()
        if file_hash in state["imports"]:
            raise DuplicateImportError(file_hash, state["imports"][file_hash]["id"])
        import_id = str(uuid.uuid4())
        state["imports"][file_hash] = {"id": import_id, "file_name": file_name,
                                       "started_at": datetime.now(timezone.utc).isoformat()}
        self._save_state(state)
        self._current = import_id
        self._batch = 0
        self._write("01_post_imports.json", {
            "file_name": file_name, "file_hash": file_hash,
            "period_start": _iso(period_start), "period_end": _iso(period_end)})
        return import_id

    def update_import(self, import_id: str, **fields: Any) -> None:
        self._current = import_id
        self._write("99_patch_imports.json", {k: _iso(v) for k, v in fields.items()})

    # --- Hulpfuncties ------------------------------------------------------------------
    def import_dir(self, import_id: str) -> Path:
        return self.directory / import_id

    def _write(self, name: str, body: Any) -> None:
        target = self.import_dir(self._current)
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding="utf-8")

    def _state(self) -> dict[str, Any]:
        if self._state_file.exists():
            return json.loads(self._state_file.read_text(encoding="utf-8"))
        return {"meters": [], "imports": {}}

    def _save_state(self, state: dict[str, Any]) -> None:
        self._state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _iso(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def create_backend() -> BackendClient:
    """Kiest de backend op basis van SES_BACKEND_MODE."""
    if config.BACKEND_MODE == "dryrun":
        return DryRunBackendClient(config.DRYRUN_DIR)
    raise NotImplementedError(
        f"SES_BACKEND_MODE={config.BACKEND_MODE!r} bestaat nog niet; alleen 'dryrun'. "
        "De HTTP-client volgt zodra de Backend API (ses-214) gemerged is.")
