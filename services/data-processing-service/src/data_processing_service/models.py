"""Datamodellen voor het importrapport: wat ging goed, wat is gemeld."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    ERROR = "error"      # regel is geweigerd en niet opgeslagen
    WARNING = "warning"  # regel is opgeslagen, maar de admin moet ernaar kijken
    INFO = "info"        # ter informatie


class Code(str, Enum):
    # csv_parser
    INVALID_NUMBER = "invalid_number"
    EMPTY_VALUE = "empty_value"
    INVALID_TIMESTAMP = "invalid_timestamp"
    MISSING_TIMEZONE = "missing_timezone"
    NOT_ON_QUARTER = "not_on_quarter"
    MISSING_METER = "missing_meter"
    METER_TOO_LONG = "meter_too_long"
    UNKNOWN_METER_TYPE = "unknown_meter_type"
    ROUNDED = "rounded"
    LOCAL_TIME_MISMATCH = "local_time_mismatch"
    # validator
    NEGATIVE_VALUE = "negative_value"
    ABOVE_LIMIT = "above_limit"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_CONFLICT = "duplicate_conflict"
    GAP = "gap"
    PARTIAL_PERIOD = "partial_period"
    # simultaneity_calculator
    SIMULTANEITY_FAILED = "simultaneity_failed"


@dataclass
class Issue:
    code: Code
    severity: Severity
    message: str
    line: int | None = None             # regelnummer in de CSV (header = regel 1)
    meter_reference: str | None = None
    ts: datetime | None = None


@dataclass
class Gap:
    """Aaneengesloten ontbrekende kwartieren van één meter: [start, end)."""
    meter_reference: str
    start: datetime
    end: datetime
    quarters: int


class CsvFormatError(Exception):
    """Het bestand als geheel is onbruikbaar (bijvoorbeeld een ontbrekende kolom)."""


@dataclass
class ImportReport:
    file_name: str
    file_hash: str
    status: str = "running"             # running, succeeded, failed, duplicate, validated
    import_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None  # exclusief: einde van het laatste kwartier
    rows_in_file: int = 0
    rows_accepted: int = 0              # = row_count in import_log
    rows_rejected: int = 0              # geweigerd door een fout (wordt een gap)
    rows_duplicate: int = 0             # dubbele regels die zijn samengevoegd
    meters: list[str] = field(default_factory=list)
    new_meters: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    simultaneity_quarters: int = 0      # recalculated quarters in community_simultaneity
    error_message: str | None = None

    def summary(self) -> dict[str, int]:
        """Aantal meldingen per code."""
        telling: dict[str, int] = {}
        for issue in self.issues:
            telling[issue.code.value] = telling.get(issue.code.value, 0) + 1
        return telling

    def to_dict(self) -> dict:
        def omzetten(waarde):
            if isinstance(waarde, datetime):
                return waarde.isoformat()
            if isinstance(waarde, Enum):
                return waarde.value
            if isinstance(waarde, dict):
                return {k: omzetten(v) for k, v in waarde.items()}
            if isinstance(waarde, list):
                return [omzetten(v) for v in waarde]
            return waarde

        data = omzetten(asdict(self))
        data["summary"] = self.summary()
        return data
