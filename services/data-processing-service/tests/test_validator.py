"""Acceptatiecriteria US1.2: dubbelen, gaps (niet als nul) en limieten per meter."""

from datetime import datetime, timezone

import pytest

from data_processing_service.csv_parser import parse_csv
from data_processing_service.models import Code, Severity
from data_processing_service.validator import limit_for, validate


def run(fixture_bytes, name):
    return validate(parse_csv(fixture_bytes(name)).rows)


def test_exacte_dubbele_een_keer_opgeslagen(fixture_bytes):
    result = run(fixture_bytes, "dubbelen.csv")
    assert any(i.code == Code.DUPLICATE_EXACT for i in result.issues)
    assert not result.rows.duplicated(["meter_reference", "ts"]).any()
    assert result.rows_duplicate == 2 and len(result.rows) == 4


def test_conflicterende_dubbele_nieuwste_wint(fixture_bytes):
    result = run(fixture_bytes, "dubbelen.csv")
    conflict = next(i for i in result.issues if i.code == Code.DUPLICATE_CONFLICT)
    assert conflict.line == 7 and "4, 7" in conflict.message
    rij = result.rows.set_index("ts").loc[datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)]
    assert rij.from_grid_kwh == pytest.approx(0.999)


def test_gap_wordt_gemeld_en_niet_als_nul_opgeslagen(fixture_bytes):
    result = run(fixture_bytes, "gaps.csv")
    kv90 = [g for g in result.gaps if g.meter_reference == "KV90"]
    assert len(kv90) == 1 and kv90[0].quarters == 2
    assert kv90[0].start == datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
    assert len(result.rows[result.rows.meter_reference == "KV90"]) == 6  # geen ingevulde rijen


def test_later_beginnende_meter_is_geen_gap(fixture_bytes):
    result = run(fixture_bytes, "gaps.csv")
    assert not [g for g in result.gaps if g.meter_reference == "KV91"]
    info = [i for i in result.issues if i.code == Code.PARTIAL_PERIOD]
    assert [i.meter_reference for i in info] == ["KV91"]


def test_negatieve_waarde_geweigerd_en_wordt_gap(fixture_bytes):
    result = run(fixture_bytes, "limieten.csv")
    neg = next(i for i in result.issues if i.code == Code.NEGATIVE_VALUE)
    assert neg.severity == Severity.ERROR and neg.line == 4
    assert result.rows_rejected == 1
    assert any(g.meter_reference == "KV90" and g.quarters == 1 for g in result.gaps)


def test_boven_limiet_wel_opgeslagen_met_waarschuwing(fixture_bytes):
    result = run(fixture_bytes, "limieten.csv")
    above = {i.meter_reference: i for i in result.issues if i.code == Code.ABOVE_LIMIT}
    assert set(above) == {"KV90", "GV90"}
    assert all(i.severity == Severity.WARNING for i in above.values())
    assert (result.rows["from_grid_kwh"] == 20.0).any()


def test_limiet_per_meter():
    assert limit_for("KV01") == 13.8
    assert limit_for("GV03") == 43.3
    assert limit_for("meter_0123456789abcdef01234567") == 43.3
    assert limit_for("KV01", {"KV01": 5.0}) == 5.0


def test_echte_export_zonder_meldingen_behalve_periode(fixture_bytes):
    result = run(fixture_bytes, "testset_wintertijd_2026.csv")
    assert {i.code for i in result.issues} == {Code.DUPLICATE_EXACT, Code.ABOVE_LIMIT,
                                               Code.GAP, Code.PARTIAL_PERIOD}
