"""Import orchestrator (component 'Import orchestrator' in C4 3.3).

Runs the import steps in order:
    register -> csv_parser -> validator -> add meters -> upsert readings -> finish
    -> recalculate simultaneity

Not in this story yet (follow later): meter_linker, training_notifier.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from . import config
from .backend_client import BackendClient, BackendError, DuplicateImportError
from .csv_parser import parse_csv
from .models import Code, CsvFormatError, ImportReport, Issue, Severity
from .simultaneity_calculator import calculate
from .validator import validate


def register_import(content: bytes, file_name: str, backend: BackendClient) -> ImportReport:
    """Stap 1 (Import endpoint): bestandsnaam en hash vastleggen in import_log."""
    report = ImportReport(file_name=file_name, file_hash=hashlib.sha256(content).hexdigest())
    try:
        report.import_id = backend.start_import(file_name, report.file_hash)
    except DuplicateImportError as exc:
        report.status = "duplicate"
        report.error_message = str(exc)
    except BackendError as exc:
        report.status = "failed"
        report.error_message = str(exc)
    return report


def process_import(report: ImportReport, content: bytes, backend: BackendClient | None,
                   meter_limits: dict[str, float] | None = None) -> ImportReport:
    """Stap 2 t/m 6. Zonder backend (None) wordt alleen gevalideerd en niets weggeschreven."""
    try:
        parsed = parse_csv(content)
        validated = validate(parsed.rows, meter_limits)
    except CsvFormatError as exc:
        return _fail(report, backend, str(exc))

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
        backend.update_import(report.import_id, status="succeeded",
                              period_start=report.period_start, period_end=report.period_end,
                              row_count=report.rows_accepted,
                              new_meter_count=len(report.new_meters))
        report.status = "succeeded"
    except BackendError as exc:
        return _fail(report, backend, f"wegschrijven mislukt: {exc}")

    # The readings are stored, so the import succeeded. If the recalculation fails, add a
    # warning: importing the same file again is not possible (409); recover with
    # python -m data_processing_service --recalculate START END.
    if report.period_start is not None:
        try:
            report.simultaneity_quarters = recalculate_simultaneity(
                backend, report.period_start, report.period_end)
        except BackendError as exc:
            report.issues.append(Issue(
                Code.SIMULTANEITY_FAILED, Severity.WARNING,
                f"simultaneity not recalculated: {exc}. Retry with --recalculate "
                f"{report.period_start.isoformat()} {report.period_end.isoformat()}"))
    return report


def recalculate_simultaneity(backend: BackendClient, start: datetime, end: datetime) -> int:
    """Recalculate the simultaneity of [start, end) from all readings, one week at a time.

    Each chunk replaces the existing rows in community_simultaneity, so running it again gives
    the same result. A chunk without readings is skipped (PUT needs at least one row).
    Returns the number of quarters written.
    """
    step = timedelta(days=config.SIMULTANEITY_CHUNK_DAYS)
    written = 0
    while start < end:
        chunk_end = min(start + step, end)
        rows = [q.to_payload() for q in calculate(backend.list_readings(start, chunk_end))]
        if rows:
            written += backend.replace_simultaneity(start, chunk_end, rows)
        start = chunk_end
    return written


def run_import(content: bytes, file_name: str, backend: BackendClient | None,
               meter_limits: dict[str, float] | None = None) -> ImportReport:
    """Volledige import in één keer (CLI). backend=None: alleen valideren."""
    if backend is None:
        report = ImportReport(file_name, hashlib.sha256(content).hexdigest())
        return process_import(report, content, None, meter_limits)
    report = register_import(content, file_name, backend)
    if report.status != "running":
        return report
    return process_import(report, content, backend, meter_limits)


def readings_payload(rows: pd.DataFrame) -> list[dict[str, Any]]:
    """Body voor PUT /readings. kWh als tekst met 3 decimalen, zoals Decimal in de API."""
    return [
        {"meter_reference": r.meter_reference, "ts": r.ts.isoformat(),
         "to_grid_kwh": f"{r.to_grid_kwh:.3f}", "from_grid_kwh": f"{r.from_grid_kwh:.3f}"}
        for r in rows.itertuples()
    ]


def _fail(report: ImportReport, backend: BackendClient | None, message: str) -> ImportReport:
    """Import als mislukt markeren, ook in import_log als dat nog lukt."""
    report.status = "failed"
    report.error_message = message
    if backend is not None and report.import_id:
        try:
            backend.update_import(report.import_id, status="failed", error_message=message[:1000])
        except BackendError:
            pass  # Backend API onbereikbaar: de fout staat al in het rapport
    return report
