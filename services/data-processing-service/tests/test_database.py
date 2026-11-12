"""Controleert of een import echt goed in de database terechtkomt.

Draait tegen de echte Backend API en database in de dev-container en wordt anders
overgeslagen. Elke test importeert een bestand uit fixtures/ en kijkt daarna met SQL in
import_log, meters en readings. Testdata wordt voor en na elke test opgeruimd.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from data_processing_service.backend_client import BackendClient
from data_processing_service.import_orchestrator import run_import

FIXTURES = Path(__file__).parent / "fixtures"
TEST_METERS = ["GV90", "KV90", "KV91"]
PREFIX = "pytest-"  # bestandsnaam in import_log, zodat opruimen alleen testimports raakt


def _backend_bereikbaar() -> bool:
    url = os.environ.get("BACKEND_API_URL", "")
    if not url or not os.environ.get("DATABASE_URL"):
        return False
    try:
        return httpx.get(url.removesuffix("/v1") + "/health", timeout=3).is_success
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _backend_bereikbaar(),
                                reason="Backend API of database niet bereikbaar (alleen in de dev-container)")


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)


@pytest.fixture
def db():
    """Verbinding met de database als eigenaar (DATABASE_URL), met opruimen ervoor en erna."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, row_factory=dict_row) as conn:
        def opruimen():
            conn.execute("DELETE FROM readings WHERE meter_reference = ANY(%s)", [TEST_METERS])
            conn.execute("DELETE FROM meters WHERE meter_reference = ANY(%s)", [TEST_METERS])
            conn.execute("DELETE FROM import_log WHERE file_name LIKE %s", [PREFIX + "%"])

        opruimen()
        yield conn
        opruimen()


def importeer(name: str, content: bytes | None = None):
    content = content if content is not None else (FIXTURES / name).read_bytes()
    backend = BackendClient()
    try:
        return run_import(content, PREFIX + name, backend)
    finally:
        backend.close()


def import_log(db, name: str) -> list[dict]:
    return db.execute("SELECT * FROM import_log WHERE file_name = %s", [PREFIX + name]).fetchall()


def readings(db, meter: str, start: str, end: str) -> list[dict]:
    return db.execute("SELECT ts, to_grid_kwh, from_grid_kwh FROM readings "
                      "WHERE meter_reference = %s AND ts >= %s AND ts < %s ORDER BY ts",
                      [meter, utc(start), utc(end)]).fetchall()


def test_import_log(db):
    report = importeer("testset_wintertijd_2026.csv")
    assert report.status == "succeeded", report.error_message

    (row,) = import_log(db, "testset_wintertijd_2026.csv")
    assert row["status"] == "succeeded" and row["error_message"] is None
    assert row["row_count"] == 476 and row["new_meter_count"] == 3
    assert row["period_start"] == utc("2026-10-24 00:00")
    assert row["period_end"] == utc("2026-10-26 00:00")
    assert row["file_hash"] == report.file_hash


def test_meters_aangemaakt_zonder_deelnemer(db):
    importeer("testset_wintertijd_2026.csv")
    rows = db.execute("SELECT meter_reference, participant_id FROM meters "
                      "WHERE meter_reference = ANY(%s) ORDER BY 1", [TEST_METERS]).fetchall()
    assert [r["meter_reference"] for r in rows] == TEST_METERS
    assert all(r["participant_id"] is None for r in rows)


def test_aantal_metingen_per_meter(db):
    importeer("testset_wintertijd_2026.csv")
    rows = db.execute("SELECT meter_reference, count(*) AS n FROM readings "
                      "WHERE meter_reference = ANY(%s) GROUP BY 1 ORDER BY 1", [TEST_METERS]).fetchall()
    # KV91 mist 4 kwartieren (gap), de dubbele en de foute regel staan er niet extra in
    assert {r["meter_reference"]: r["n"] for r in rows} == {"GV90": 96, "KV90": 192, "KV91": 188}


def test_waarden_met_decimale_komma(db):
    importeer("testset_wintertijd_2026.csv")
    (eerste,) = readings(db, "KV90", "2026-10-24 00:00", "2026-10-24 00:15")
    assert eerste["to_grid_kwh"] == Decimal("0.000") and eerste["from_grid_kwh"] == Decimal("0.050")
    (boven_limiet,) = readings(db, "KV90", "2026-10-24 02:30", "2026-10-24 02:45")
    assert boven_limiet["from_grid_kwh"] == Decimal("15.500")  # "15,5" in de CSV, wel opgeslagen


def test_wintertijd_doorlopend_in_utc(db):
    importeer("testset_wintertijd_2026.csv")
    rows = readings(db, "KV90", "2026-10-25 00:00", "2026-10-25 02:00")
    # lokaal komt 02:00-03:00 twee keer voor; in UTC zijn het 8 opeenvolgende kwartieren
    assert [r["ts"] for r in rows] == [utc("2026-10-25 00:00") + i * (utc("2026-10-25 00:15") - utc("2026-10-25 00:00"))
                                       for i in range(8)]


def test_gap_is_leeg_en_niet_nul(db):
    importeer("testset_wintertijd_2026.csv")
    assert readings(db, "KV91", "2026-10-24 14:30", "2026-10-24 15:30") == []
    assert len(readings(db, "KV91", "2026-10-24 14:00", "2026-10-24 16:00")) == 4


def test_nieuwste_dubbele_waarde_opgeslagen(db):
    assert importeer("dubbelen.csv").status == "succeeded"
    (rij,) = readings(db, "KV90", "2026-06-01 10:30", "2026-06-01 10:45")
    assert rij["from_grid_kwh"] == Decimal("0.999")
    assert len(readings(db, "KV90", "2026-06-01 10:00", "2026-06-01 11:00")) == 4


def test_negatief_geweigerd_en_boven_limiet_opgeslagen(db):
    assert importeer("limieten.csv").status == "succeeded"
    assert readings(db, "KV90", "2026-06-01 10:30", "2026-06-01 10:45") == []  # negatief
    (kv,) = readings(db, "KV90", "2026-06-01 10:15", "2026-06-01 10:30")
    assert kv["from_grid_kwh"] == Decimal("20.000")
    (gv,) = readings(db, "GV90", "2026-06-01 10:30", "2026-06-01 10:45")
    assert gv["to_grid_kwh"] == Decimal("50.000")


def test_overlappende_exports_geven_geen_dubbelen(db):
    importeer("dst_oktober.csv")  # KV90, 24 okt 23:30 t/m 25 okt 01:45
    importeer("testset_wintertijd_2026.csv")  # overlapt die periode
    assert len(readings(db, "KV90", "2026-10-24 00:00", "2026-10-26 00:00")) == 192
    (rij,) = readings(db, "KV90", "2026-10-24 23:30", "2026-10-24 23:45")
    assert rij["from_grid_kwh"] == Decimal("0.070")  # waarde uit de laatste import


def test_zelfde_bestand_een_keer_in_import_log(db):
    importeer("dst_maart.csv")
    assert importeer("dst_maart.csv").status == "duplicate"
    assert len(import_log(db, "dst_maart.csv")) == 1


def test_mislukte_import_in_import_log(db):
    report = importeer("kapot.csv", b"meter_reference,interval_start\nKV90,2026-06-01\n")
    assert report.status == "failed"
    (row,) = import_log(db, "kapot.csv")
    assert row["status"] == "failed" and "from_grid_kWh" in row["error_message"]
    assert db.execute("SELECT count(*) AS n FROM readings WHERE meter_reference = 'KV90'").fetchone()["n"] == 0
