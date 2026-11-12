"""Acceptatiecriteria US1.2: decimale komma's, quoted values en UTC rond zomer- en wintertijd."""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from data_processing_service.csv_parser import parse_csv
from data_processing_service.models import Code, CsvFormatError, Severity

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def codes(result):
    return [i.code for i in result.issues]


def test_decimale_komma_en_quotes():
    result = parse_csv(read("testset_wintertijd_2026.csv"))
    rij = result.rows.set_index("line").loc[12]
    assert rij.from_grid_kwh == pytest.approx(15.5)  # "15,5" in de CSV
    assert result.rows["from_grid_kwh"].dtype == float


def test_bom_wordt_genegeerd():
    assert read("testset_wintertijd_2026.csv").startswith(b"\xef\xbb\xbf")
    assert "meter_reference" in parse_csv(read("testset_wintertijd_2026.csv")).rows.columns


def test_tijd_is_utc_kwartier():
    ts = parse_csv(read("testset_wintertijd_2026.csv")).rows["ts"]
    assert str(ts.dt.tz) == "UTC"
    assert ts.iloc[0] == pd.Timestamp("2026-10-24 00:00", tz="UTC")


def test_zomertijd_maart_loopt_door_in_utc():
    result = parse_csv(read("dst_maart.csv"))
    assert result.issues == []
    assert (result.rows["ts"].diff().dropna() == pd.Timedelta(minutes=15)).all()


def test_wintertijd_oktober_geen_dubbelen_in_utc():
    result = parse_csv(read("dst_oktober.csv"))
    assert result.issues == []  # nl_time 02:00-02:45 komt twee keer voor: geen fout
    assert result.rows["ts"].is_unique
    assert result.rows["ts"].iloc[2] == pd.Timestamp("2026-10-25 00:00", tz="UTC")
    assert result.rows["ts"].iloc[6] == pd.Timestamp("2026-10-25 01:00", tz="UTC")


@pytest.mark.parametrize("line, code", [
    (4, Code.INVALID_NUMBER),
    (5, Code.EMPTY_VALUE),
    (6, Code.NOT_ON_QUARTER),
    (7, Code.MISSING_TIMEZONE),
    (8, Code.INVALID_TIMESTAMP),
    (9, Code.MISSING_METER),
])
def test_foute_regel_wordt_geweigerd(line, code):
    result = parse_csv(read("fouten.csv"))
    issue = next(i for i in result.issues if i.line == line)
    assert issue.code == code and issue.severity == Severity.ERROR
    assert line not in result.rows["line"].tolist()


def test_foute_regels_houden_de_rest_niet_tegen():
    result = parse_csv(read("fouten.csv"))
    assert result.rows_in_file == 12
    assert result.rows_rejected == 6
    assert sorted(result.rows["line"]) == [2, 3, 10, 11, 12, 13]


def test_waarschuwingen_worden_wel_opgeslagen():
    result = parse_csv(read("fouten.csv"))
    by_line = {i.line: i for i in result.issues}
    assert by_line[10].code == Code.ROUNDED
    assert result.rows.set_index("line").loc[10, "from_grid_kwh"] == pytest.approx(0.123)
    assert by_line[11].code == Code.LOCAL_TIME_MISMATCH
    assert by_line[12].code == Code.UNKNOWN_METER_TYPE
    assert 13 not in by_line  # meter_ + 24 hex is een geldig pseudoniem


def test_ontbrekende_kolom_is_fataal():
    csv = b'meter_reference,interval_start,interval_time,to_grid_kWh\nKV01,2026-06-01,10:30:00+00,"0,0"\n'
    with pytest.raises(CsvFormatError, match="from_grid_kWh"):
        parse_csv(csv)


def test_leeg_bestand_is_fataal():
    with pytest.raises(CsvFormatError):
        parse_csv(b"")


@pytest.mark.parametrize("tijd", ["10:30:00+00", "10:30:00+00:00", "10:30:00+0000",
                                  "10:30:00Z", "12:30:00+02", "10:30+00"])
def test_tijdzone_notaties(tijd):
    csv = ("meter_reference,interval_start,interval_time,to_grid_kWh,from_grid_kWh\n"
           f'KV01,2026-06-01,{tijd},"0,0","0,1"\n').encode()
    result = parse_csv(csv)
    assert result.rows["ts"].iloc[0] == datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
