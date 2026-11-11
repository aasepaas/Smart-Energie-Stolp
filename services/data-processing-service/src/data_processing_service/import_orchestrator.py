"""Import orchestrator (component 'Import orchestrator' in C4 3.3).

Voert de importstappen in volgorde uit:
    registreren -> csv_parser -> validator -> meters toevoegen -> metingen upserten -> afronden

Nog niet in deze story (volgen later): meter_linker, simultaneity_calculator, training_notifier.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from . import config
from .backend_client import BackendClient, DuplicateImportError
from .csv_parser import parse_csv
from .models import CsvFormatError, ImportReport
from .validator import validate


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def register_import(content: bytes, file_name: str, backend: BackendClient) -> ImportReport:
    """Stap 1 (Import endpoint): bestandsnaam en hash vastleggen. 409 -> status 'duplicate'."""
    report = ImportReport(file_name=file_name, file_hash=file_hash(content))
    try:
        report.import_id = backend.start_import(file_name, report.file_hash)
    except DuplicateImportError as exc:
        report.status = "duplicate"
        report.import_id = exc.existing_id
        report.error_message = str(exc)
    return report


def process_import(report: ImportReport, content: bytes, backend: BackendClient | None,
                   meter_limits: dict[str, float] | None = None) -> ImportReport:
    """Stap 2 t/m 6. Zonder backend (None) wordt alleen gevalideerd en niets weggeschreven."""
    try:
        parsed = parse_csv(content)
        validated = validate(parsed.rows, meter_limits)
    except CsvFormatError as exc:
        report.status = "failed"
        report.error_message = str(exc)
        if backend is not None and report.import_id:
            backend.update_import(report.import_id, status="failed", error_message=str(exc))
        return report

    rows = validated.rows
    report.rows_in_file = parsed.rows_in_file
    report.rows_rejected = parsed.rows_rejected + validated.rows_rejected
    report.rows_duplicate = validated.rows_duplicate
    report.rows_accepted = len(rows)
    report.gaps = validated.gaps
    report.issues = sorted(parsed.issues + validated.issues,
                           key=lambda i: (i.line is None, i.line or 0, i.meter_reference or ""))
    report.meters = sorted(rows["meter_reference"].unique().tolist())
    if not rows.empty:
        report.period_start = rows["ts"].min().to_pydatetime()
        report.period_end = (rows["ts"].max() + pd.Timedelta(minutes=15)).to_pydatetime()

    if backend is None:
        report.status = "validated"
        return report

    try:
        known = set(backend.list_meters())
        report.new_meters = [m for m in report.meters if m not in known]
        if report.new_meters:
            backend.add_meters(report.new_meters)  # eerst meters: readings verwijst ernaar (FK)
        payload = readings_payload(rows)
        for start in range(0, len(payload), config.MAX_BATCH):
            backend.upsert_readings(payload[start:start + config.MAX_BATCH])
        report.status = "succeeded"
        backend.update_import(report.import_id, status="succeeded",
                              period_start=report.period_start, period_end=report.period_end,
                              row_count=report.rows_accepted,
                              new_meter_count=len(report.new_meters))
    except Exception as exc:  # backend onbereikbaar of weigert: import markeren als mislukt
        report.status = "failed"
        report.error_message = f"wegschrijven mislukt: {exc}"
        backend.update_import(report.import_id, status="failed",
                              error_message=report.error_message)
    return report


def run_import(content: bytes, file_name: str, backend: BackendClient | None,
               meter_limits: dict[str, float] | None = None) -> ImportReport:
    """Volledige import in één keer (CLI). backend=None: alleen valideren."""
    if backend is None:
        return process_import(ImportReport(file_name, file_hash(content)), content, None,
                              meter_limits)
    report = register_import(content, file_name, backend)
    if report.status == "duplicate":
        return report
    return process_import(report, content, backend, meter_limits)


def readings_payload(rows: pd.DataFrame) -> list[dict[str, Any]]:
    """Body voor PUT /readings. kWh als tekst met 3 decimalen, zoals Decimal in de API."""
    return [
        {"meter_reference": r.meter_reference, "ts": r.ts.isoformat(),
         "to_grid_kwh": f"{r.to_grid_kwh:.3f}", "from_grid_kwh": f"{r.from_grid_kwh:.3f}"}
        for r in rows.itertuples()
    ]


def save_report(report: ImportReport, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "report.json"
    path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    return path
