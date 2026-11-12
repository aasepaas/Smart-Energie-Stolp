"""Handmatig importeren vanaf de command line.

    python -m data_processing_service <bestand.csv>                 importeren via de Backend API
    python -m data_processing_service <bestand.csv> --validate-only alleen controleren
    python -m data_processing_service <bestand.csv> --all           alle meldingen tonen
    python -m data_processing_service <bestand.csv> --json          rapport als JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import backend_client
from .backend_client import BackendError
from .import_orchestrator import run_import
from .models import ImportReport

EXIT_CODES = {"succeeded": 0, "validated": 0, "failed": 1, "duplicate": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m data_processing_service",
                                     description="Meterdata-CSV importeren en valideren")
    parser.add_argument("file", type=Path)
    parser.add_argument("--validate-only", action="store_true", help="niets wegschrijven")
    parser.add_argument("--all", action="store_true", help="alle meldingen tonen (standaard 20)")
    parser.add_argument("--json", action="store_true", help="rapport als JSON")
    args = parser.parse_args(argv)

    if not args.file.is_file():
        parser.error(f"bestand niet gevonden: {args.file}")
    backend = None
    if not args.validate_only:
        try:
            backend = backend_client.create_backend()
        except BackendError as exc:
            parser.error(str(exc))
    try:
        report = run_import(args.file.read_bytes(), args.file.name, backend)
    finally:
        if backend is not None:
            backend.close()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print_report(report, show_all=args.all)
    return EXIT_CODES.get(report.status, 1)


def print_report(report: ImportReport, show_all: bool = False) -> None:
    print(f"Bestand     {report.file_name}")
    print(f"Status      {report.status}" + (f" ({report.error_message})" if report.error_message else ""))
    if report.import_id:
        print(f"Import-id   {report.import_id}")
    if report.status == "duplicate":
        return
    if report.period_start:
        print(f"Periode     {report.period_start:%Y-%m-%d %H:%M} tot {report.period_end:%Y-%m-%d %H:%M} UTC")
    print(f"Regels      {report.rows_in_file} in bestand, {report.rows_accepted} opgeslagen, "
          f"{report.rows_rejected} geweigerd, {report.rows_duplicate} dubbel")
    print(f"Meters      {len(report.meters)}" +
          (f", nieuw: {', '.join(report.new_meters)}" if report.new_meters else ""))
    print(f"Gaps        {len(report.gaps)} ({sum(g.quarters for g in report.gaps)} kwartieren)")
    if report.issues:
        print("\nMeldingen per soort: " + ", ".join(f"{k} {v}" for k, v in report.summary().items()))
        shown = report.issues if show_all else report.issues[:20]
        for issue in shown:
            where = f"regel {issue.line}" if issue.line else "-"
            print(f"  [{issue.severity.value:7}] {where:>10}  {issue.meter_reference or '':6}  {issue.message}")
        if len(shown) < len(report.issues):
            print(f"  ... en nog {len(report.issues) - len(shown)} (gebruik --all)")


if __name__ == "__main__":
    sys.exit(main())
