"""Import end-to-end: orchestrator, backend client, endpoint en CLI.

Deze tests praten met een nagebootste Backend API (httpx.MockTransport) die dezelfde
paden, statuscodes en regels heeft als services/backend-api. Of de data echt in de
database komt, test test_database.py.
"""

import hashlib
import json
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from data_processing_service import backend_client, config
from data_processing_service.__main__ import main
from data_processing_service.backend_client import BackendClient
from data_processing_service.import_orchestrator import run_import

FIXTURES = Path(__file__).parent / "fixtures"
REPO_DATA = Path(__file__).resolve().parents[3] / "data" / "meterdata.csv"
TOKEN = "test-processing"


def read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeBackendAPI:
    """Bootst de Backend API na: token, 409 op dezelfde hash, FK meters -> readings, max batch."""

    def __init__(self):
        self.meters: set[str] = set()
        self.imports: dict[str, dict] = {}   # id -> import_log-rij
        self.readings: dict[tuple, dict] = {}
        self.calls: list[str] = []
        self.fail_readings = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != f"Bearer {TOKEN}":
            return httpx.Response(401, json={"detail": "unknown service token"})
        path = request.url.path.removeprefix("/v1")
        body = json.loads(request.content) if request.content else None
        self.calls.append(f"{request.method} {path}")

        if request.method == "GET" and path == "/meters":
            return httpx.Response(200, json=[{"meter_reference": m, "participant_id": None}
                                             for m in sorted(self.meters)])
        if request.method == "POST" and path == "/meters":
            new = set(body["meter_references"]) - self.meters
            self.meters |= new
            return httpx.Response(200, json={"count": len(new)})
        if request.method == "PUT" and path == "/readings":
            if self.fail_readings:
                return httpx.Response(500, text="Internal Server Error")
            if len(body) > config.MAX_BATCH:
                return httpx.Response(422, json={"detail": "too many rows"})
            if any(r["meter_reference"] not in self.meters for r in body):
                return httpx.Response(422, json={"detail": "Item doesnt exist in the database"})
            for r in body:
                self.readings[(r["meter_reference"], r["ts"])] = r
            return httpx.Response(200, json={"count": len(body)})
        if request.method == "POST" and path == "/imports":
            if any(i["file_hash"] == body["file_hash"] for i in self.imports.values()):
                return httpx.Response(409, json={"detail": "Already exists"})
            row = {"id": str(uuid.uuid4()), "status": "running", **body}
            self.imports[row["id"]] = row
            return httpx.Response(201, json=row)
        if request.method == "PATCH" and path.startswith("/imports/"):
            self.imports[path.split("/")[-1]].update(body)
            return httpx.Response(200, json=self.imports[path.split("/")[-1]])
        return httpx.Response(404, json={"detail": "Not Found"})

    def client(self, token: str = TOKEN) -> BackendClient:
        http = httpx.Client(base_url="http://backend-api:8001/v1",
                            headers={"Authorization": f"Bearer {token}"},
                            transport=httpx.MockTransport(self.handler))
        return BackendClient(http=http)


@pytest.fixture
def api(monkeypatch):
    fake = FakeBackendAPI()
    monkeypatch.setattr(backend_client, "create_backend", fake.client)
    return fake


def only_import(api) -> dict:
    (row,) = api.imports.values()
    return row


def test_import_schrijft_naar_backend_api(api):
    report = run_import(read("testset_wintertijd_2026.csv"), "test.csv", api.client())
    assert report.status == "succeeded"
    assert report.rows_accepted == 476 and report.new_meters == ["GV90", "KV90", "KV91"]
    assert api.calls == ["POST /imports", "GET /meters", "POST /meters", "PUT /readings",
                         f"PATCH /imports/{report.import_id}"]
    assert api.readings[("KV90", "2026-10-24T00:00:00+00:00")] == {
        "meter_reference": "KV90", "ts": "2026-10-24T00:00:00+00:00",
        "to_grid_kwh": "0.000", "from_grid_kwh": "0.050"}
    row = only_import(api)
    assert row["status"] == "succeeded" and row["row_count"] == 476
    assert row["file_hash"] == hashlib.sha256(read("testset_wintertijd_2026.csv")).hexdigest()
    assert row["period_end"] == "2026-10-26T00:00:00+00:00"


def test_zelfde_bestand_twee_keer_is_duplicate(api):
    run_import(read("dst_maart.csv"), "a.csv", api.client())
    second = run_import(read("dst_maart.csv"), "a.csv", api.client())
    assert second.status == "duplicate" and len(api.imports) == 1


def test_bekende_meters_worden_niet_opnieuw_toegevoegd(api):
    run_import(read("dst_maart.csv"), "a.csv", api.client())
    report = run_import(read("dst_oktober.csv"), "b.csv", api.client())
    assert report.new_meters == [] and api.calls.count("POST /meters") == 1


def test_grote_import_in_batches(api, monkeypatch):
    monkeypatch.setattr(config, "MAX_BATCH", 100)
    run_import(read("testset_wintertijd_2026.csv"), "t.csv", api.client())
    assert api.calls.count("PUT /readings") == 5 and len(api.readings) == 476


def test_fataal_formaat_markeert_import_als_mislukt(api):
    report = run_import(b"meter_reference,interval_start\nKV01,2026-06-01\n", "x.csv", api.client())
    assert report.status == "failed" and "from_grid_kWh" in report.error_message
    assert only_import(api)["status"] == "failed"


def test_backend_fout_markeert_import_als_mislukt(api):
    api.fail_readings = True
    report = run_import(read("dst_maart.csv"), "a.csv", api.client())
    assert report.status == "failed" and "500" in report.error_message
    assert only_import(api)["status"] == "failed"


def test_verkeerd_token(api):
    report = run_import(read("dst_maart.csv"), "a.csv", api.client(token="fout"))
    assert report.status == "failed" and "401" in report.error_message


def test_backend_onbereikbaar():
    client = BackendClient(base_url="http://127.0.0.1:9/v1", token="x")
    report = run_import(read("dst_maart.csv"), "a.csv", client)
    assert report.status == "failed" and "niet bereikbaar" in report.error_message


def test_zonder_instellingen(monkeypatch):
    monkeypatch.delenv("BACKEND_API_URL", raising=False)
    with pytest.raises(backend_client.BackendError, match="BACKEND_API_URL"):
        BackendClient()


def test_alleen_valideren_schrijft_niets(api):
    report = run_import(read("fouten.csv"), "f.csv", backend=None)
    assert report.status == "validated" and report.rows_rejected == 6
    assert api.calls == []


def test_endpoint_upload_en_status(api):
    from data_processing_service.import_endpoint import app
    client = TestClient(app)
    files = {"file": ("testset.csv", read("testset_wintertijd_2026.csv"), "text/csv")}

    response = client.post("/imports", files=files)
    assert response.status_code == 202
    import_id = response.json()["import_id"]
    status = client.get(f"/imports/{import_id}").json()  # TestClient wacht op de achtergrondtaak
    assert status["status"] == "succeeded" and status["summary"]["gap"] == 1
    assert len(api.readings) == 476

    assert client.post("/imports", files=files).status_code == 409


def test_endpoint_validate_only_en_fouten(api):
    from data_processing_service.import_endpoint import app
    client = TestClient(app)
    ok = client.post("/imports?validate_only=true",
                     files={"file": ("f.csv", read("fouten.csv"), "text/csv")})
    assert ok.status_code == 200 and ok.json()["rows_rejected"] == 6
    assert client.post("/imports", files={"file": ("f.txt", b"x", "text/plain")}).status_code == 415
    assert client.get("/imports/bestaat-niet").status_code == 404


def test_cli(api, capsys):
    path = FIXTURES / "gaps.csv"
    assert main([str(path)]) == 0
    assert "Gaps        1 (2 kwartieren)" in capsys.readouterr().out
    assert main([str(path)]) == 2  # tweede keer: duplicate


@pytest.mark.skipif(not REPO_DATA.exists(), reason="geen lokale export in data/")
def test_lokale_export_uit_data_map():
    report = run_import(REPO_DATA.read_bytes(), REPO_DATA.name, backend=None)
    assert report.status == "validated" and report.rows_rejected == 0
    assert not report.gaps
