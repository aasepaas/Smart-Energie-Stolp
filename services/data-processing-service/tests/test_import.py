"""Handmatige import end-to-end: orchestrator, dry-run backend, endpoint en CLI."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from data_processing_service import config
from data_processing_service.__main__ import main
from data_processing_service.backend_client import DryRunBackendClient
from data_processing_service.import_orchestrator import run_import

FIXTURES = Path(__file__).parent / "fixtures"


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()

REPO_DATA = Path(__file__).resolve().parents[3] / "data" / "meterdata.csv"


@pytest.fixture
def dryrun(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DRYRUN_DIR", tmp_path)
    return tmp_path


def test_import_schrijft_verzoeken_zoals_backend_api(dryrun):
    backend = DryRunBackendClient(dryrun)
    report = run_import(read("testset_wintertijd_2026.csv"), "test.csv", backend)
    assert report.status == "succeeded"
    assert report.rows_accepted == 476 and report.new_meters == ["GV90", "KV90", "KV91"]

    folder = backend.import_dir(report.import_id)
    readings = json.loads((folder / "03_put_readings_0001.json").read_text())
    assert len(readings) == 476
    assert readings[0] == {"meter_reference": "KV90", "ts": "2026-10-24T00:00:00+00:00",
                           "to_grid_kwh": "0.000", "from_grid_kwh": "0.050"}
    patch = json.loads((folder / "99_patch_imports.json").read_text())
    assert patch["status"] == "succeeded" and patch["row_count"] == 476


def test_zelfde_bestand_twee_keer_is_duplicate(dryrun):
    backend = DryRunBackendClient(dryrun)
    first = run_import(read("dst_maart.csv"), "a.csv", backend)
    second = run_import(read("dst_maart.csv"), "a.csv", DryRunBackendClient(dryrun))
    assert second.status == "duplicate" and second.import_id == first.import_id


def test_bekende_meters_zijn_niet_nieuw(dryrun):
    run_import(read("dst_maart.csv"), "a.csv", DryRunBackendClient(dryrun))
    report = run_import(read("dst_oktober.csv"), "b.csv", DryRunBackendClient(dryrun))
    assert report.new_meters == []


def test_grote_import_in_batches(dryrun, monkeypatch):
    monkeypatch.setattr(config, "MAX_BATCH", 100)
    backend = DryRunBackendClient(dryrun)
    report = run_import(read("testset_wintertijd_2026.csv"), "t.csv", backend)
    batches = sorted(backend.import_dir(report.import_id).glob("03_put_readings_*.json"))
    assert len(batches) == 5


def test_fataal_formaat_markeert_import_als_mislukt(dryrun):
    backend = DryRunBackendClient(dryrun)
    report = run_import(b"meter_reference,interval_start\nKV01,2026-06-01\n", "x.csv", backend)
    assert report.status == "failed" and "from_grid_kWh" in report.error_message
    patch = json.loads((backend.import_dir(report.import_id) / "99_patch_imports.json").read_text())
    assert patch["status"] == "failed"


def test_alleen_valideren_schrijft_niets(dryrun):
    report = run_import(read("fouten.csv"), "f.csv", backend=None)
    assert report.status == "validated" and report.rows_rejected == 6
    assert not any(dryrun.iterdir())


def test_endpoint_upload_en_status(dryrun):
    from data_processing_service.import_endpoint import app
    client = TestClient(app)
    files = {"file": ("testset.csv", read("testset_wintertijd_2026.csv"), "text/csv")}

    response = client.post("/imports", files=files)
    assert response.status_code == 202
    import_id = response.json()["import_id"]
    status = client.get(f"/imports/{import_id}").json()  # TestClient wacht op de achtergrondtaak
    assert status["status"] == "succeeded" and status["summary"]["gap"] == 1
    assert (dryrun / import_id / "report.json").exists()

    assert client.post("/imports", files=files).status_code == 409


def test_endpoint_validate_only_en_fouten(dryrun):
    from data_processing_service.import_endpoint import app
    client = TestClient(app)
    ok = client.post("/imports?validate_only=true",
                     files={"file": ("f.csv", read("fouten.csv"), "text/csv")})
    assert ok.status_code == 200 and ok.json()["rows_rejected"] == 6
    assert client.post("/imports", files={"file": ("f.txt", b"x", "text/plain")}).status_code == 415
    assert client.get("/imports/bestaat-niet").status_code == 404


def test_cli(dryrun, capsys):
    path = FIXTURES / "gaps.csv"
    assert main([str(path)]) == 0
    assert "Gaps        1 (2 kwartieren)" in capsys.readouterr().out
    assert main([str(path)]) == 2  # tweede keer: duplicate


@pytest.mark.skipif(not REPO_DATA.exists(), reason="geen lokale export in data/")
def test_lokale_export_uit_data_map():
    report = run_import(REPO_DATA.read_bytes(), REPO_DATA.name, backend=None)
    assert report.status == "validated" and report.rows_rejected == 0
    assert not report.gaps
