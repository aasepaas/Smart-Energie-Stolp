"""CSV parser (component 'CSV parser' in C4 3.3).

Leest de export van de netbeheerder in en zet elke regel om naar:
    meter_reference, ts (UTC), to_grid_kwh, from_grid_kwh, created_at

Keuzes:
- De tijd komt uit interval_start + interval_time; die zijn al in UTC (+00). nl_date en
  nl_time worden NIET als sleutel gebruikt: bij de overgang naar wintertijd komt 02:00-03:00
  lokaal twee keer voor. Ze dienen alleen als controle (waarschuwing bij een verschil).
- Decimale komma's ("0,031") en quoted values worden omgezet naar getallen.
- Een regel met een fout wordt geweigerd en gemeld; de rest van het bestand gaat door.
  Een geweigerd kwartier wordt daardoor vanzelf een gap, nooit een nul.
- Negatieve waarden en limieten controleert de validator, niet de parser.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .models import Code, CsvFormatError, Issue, Severity

REQUIRED_COLUMNS = ["meter_reference", "interval_start", "interval_time",
                    "to_grid_kWh", "from_grid_kWh"]
METER_PATTERN = r"(KV|GV)\d+|meter_[0-9a-f]{24}"
MAX_METER_LENGTH = 64  # varchar(64) in de database
LOCAL_TZ = "Europe/Amsterdam"
_TIME_WITH_OFFSET = re.compile(r"^(\d{2}:\d{2}(?::\d{2})?)([+-]\d{2}(?::?\d{2})?|Z)$")
_TIME_WITHOUT_OFFSET = re.compile(r"^\d{2}:\d{2}(?::\d{2})?$")


@dataclass
class ParseResult:
    rows: pd.DataFrame        # geaccepteerde regels
    issues: list[Issue]
    rows_in_file: int
    rows_rejected: int


def parse_csv(source: bytes | str | Path | BinaryIO) -> ParseResult:
    """Parse een volledige CSV. Gooit CsvFormatError als het bestand als geheel onbruikbaar is."""
    raw = _read(source)
    df = raw.copy()
    df["line"] = df.index + 2  # regel 1 is de header
    issues: list[Issue] = []
    rejected = pd.Series(False, index=df.index)

    def report(mask: pd.Series, code: Code, severity: Severity, message: str) -> None:
        nonlocal rejected
        for row in df[mask].itertuples():
            issues.append(Issue(code=code, severity=severity, line=int(row.line),
                                meter_reference=row.meter_reference or None,
                                ts=None if pd.isna(row.ts) else row.ts.to_pydatetime(),
                                message=message.format(row=row)))
        if severity is Severity.ERROR:
            rejected |= mask

    # --- Tijd: interval_start + interval_time in UTC --------------------------------
    df["ts"], ts_problems = _parse_utc(df["interval_start"], df["interval_time"])
    report(ts_problems == "missing_timezone", Code.MISSING_TIMEZONE, Severity.ERROR,
           "interval_time '{row.interval_time}' heeft geen tijdzone; verwacht bijvoorbeeld 10:30:00+00")
    report(ts_problems == "invalid", Code.INVALID_TIMESTAMP, Severity.ERROR,
           "ongeldige datum/tijd '{row.interval_start} {row.interval_time}'")
    off_quarter = df["ts"].notna() & ((df["ts"].dt.minute % 15 != 0) | (df["ts"].dt.second != 0))
    report(off_quarter, Code.NOT_ON_QUARTER, Severity.ERROR,
           "tijd {row.interval_time} valt niet op een kwartier")
    df.loc[off_quarter, "ts"] = pd.NaT

    # --- Meter ------------------------------------------------------------------------
    report(df["meter_reference"] == "", Code.MISSING_METER, Severity.ERROR,
           "meter_reference ontbreekt")
    too_long = df["meter_reference"].str.len() > MAX_METER_LENGTH
    report(too_long, Code.METER_TOO_LONG, Severity.ERROR,
           f"meter_reference is langer dan {MAX_METER_LENGTH} tekens")
    unknown = ((df["meter_reference"] != "") & ~too_long
               & ~df["meter_reference"].str.fullmatch(METER_PATTERN))
    report(unknown, Code.UNKNOWN_METER_TYPE, Severity.WARNING,
           "meter_reference '{row.meter_reference}' is geen KV-, GV- of meter_-nummer; "
           "wel opgeslagen, met de GV-limiet")

    # --- Energie: decimale komma ------------------------------------------------------
    for column, target in (("to_grid_kWh", "to_grid_kwh"), ("from_grid_kWh", "from_grid_kwh")):
        values, empty, invalid, rounded = _parse_kwh(df[column])
        df[target] = values
        report(empty, Code.EMPTY_VALUE, Severity.ERROR, f"{column} is leeg")
        report(invalid, Code.INVALID_NUMBER, Severity.ERROR,
               f"{column} '{{row.{column}}}' is geen getal")
        report(rounded, Code.ROUNDED, Severity.WARNING,
               f"{column} '{{row.{column}}}' heeft meer dan 3 decimalen; afgerond op 3")

    # --- Optioneel: aanmaakmoment (voor dubbelen) en controle op lokale tijd -----------
    if {"created_date", "created_time"} <= set(df.columns):
        df["created_at"], _ = _parse_utc(df["created_date"], df["created_time"])
    else:
        df["created_at"] = pd.NaT

    if {"nl_date", "nl_time"} <= set(df.columns):
        expected = df["ts"].dt.tz_convert(LOCAL_TZ).dt.strftime("%Y-%m-%d %H:%M:%S")
        actual = df["nl_date"] + " " + df["nl_time"].str.slice(0, 8)
        mismatch = df["ts"].notna() & (expected != actual)
        df["expected_local"] = expected
        report(mismatch, Code.LOCAL_TIME_MISMATCH, Severity.WARNING,
               "nl_date/nl_time '{row.nl_date} {row.nl_time}' past niet bij UTC-tijd "
               "(verwacht {row.expected_local}); UTC is aangehouden")

    accepted = df.loc[~rejected, ["line", "meter_reference", "ts", "to_grid_kwh",
                                  "from_grid_kwh", "created_at"]].reset_index(drop=True)
    issues.sort(key=lambda i: i.line or 0)
    return ParseResult(rows=accepted, issues=issues, rows_in_file=len(df),
                       rows_rejected=int(rejected.sum()))


def _read(source: bytes | str | Path | BinaryIO) -> pd.DataFrame:
    if isinstance(source, (str, Path)):
        source = Path(source).read_bytes()
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    try:
        df = pd.read_csv(source, sep=",", quotechar='"', dtype=str, keep_default_na=False,
                         encoding="utf-8-sig", skipinitialspace=True)
    except pd.errors.EmptyDataError as exc:
        raise CsvFormatError("het bestand is leeg") from exc
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise CsvFormatError(f"het bestand is geen geldige CSV: {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CsvFormatError(f"verplichte kolom(men) ontbreken: {', '.join(missing)}")
    if df.empty:
        raise CsvFormatError("het bestand bevat geen meetregels")
    return df.apply(lambda col: col.str.strip())


def _parse_utc(dates: pd.Series, times: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Datum + tijd met offset naar een UTC-timestamp.

    Geeft ook per regel het probleem terug: "" (geen), "missing_timezone" of "invalid".
    """
    parts = times.str.extract(_TIME_WITH_OFFSET)
    hms = parts[0].where(parts[0].str.len() != 5, parts[0] + ":00")  # 10:30 -> 10:30:00
    offset = (parts[1].str.replace("Z", "+00", regex=False)
              .str.replace(r"^([+-]\d{2})$", r"\1:00", regex=True)
              .str.replace(r"^([+-]\d{2})(\d{2})$", r"\1:\2", regex=True))
    text = dates.where(dates.str.fullmatch(r"\d{4}-\d{2}-\d{2}")) + "T" + hms + offset
    ts = pd.to_datetime(text, format="ISO8601", utc=True, errors="coerce")

    problems = pd.Series("", index=dates.index)
    problems[ts.isna()] = "invalid"
    problems[ts.isna() & times.str.fullmatch(_TIME_WITHOUT_OFFSET.pattern)] = "missing_timezone"
    return ts, problems


def _parse_kwh(values: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """'0,031' -> 0.031. Geeft (getallen, leeg, ongeldig, afgerond) terug."""
    normalised = values.str.replace(",", ".", regex=False)
    empty = values == ""
    valid = normalised.str.fullmatch(r"-?\d+(\.\d+)?")
    invalid = ~empty & ~valid
    decimals = normalised.str.extract(r"\.(\d+)$")[0].str.len().fillna(0)
    rounded = valid & (decimals > 3)
    numbers = pd.to_numeric(normalised.where(valid), errors="coerce").round(3)
    return numbers, empty, invalid, rounded
