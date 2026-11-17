"""Upload handler: checks and forwarding, with a fake Data processing service.

No database needed: the upload endpoint does not use it, and the TestClient is used
without `with`, so the lifespan (connection pool) does not start.
"""

import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from frontend_api import authentication, upload_handler
from frontend_api.authentication import Principal
from frontend_api.main import app

ADMIN = Principal(uuid.uuid4(), "administrator", None)
PARTICIPANT = Principal(uuid.uuid4(), "participant", uuid.uuid4())
CSV = b"meter_reference,interval_start,interval_time,to_grid_kWh,from_grid_kWh\n"


def auth(user: Principal) -> dict:
    return {"Authorization": f"Bearer {authentication.create_access_token(user)}"}


@pytest.fixture
def processing():
    """Fake processing service; `calls` records what it received."""
    calls = []
    answer = {"status": 202, "json": {"import_id": "abc", "status": "running"}}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if answer.get("error"):
            raise answer["error"]
        return httpx.Response(answer["status"], json=answer["json"])

    def client():
        transport = httpx.MockTransport(handler)
        with httpx.Client(base_url="http://processing", transport=transport) as c:
            yield c

    app.dependency_overrides[upload_handler.get_processing_client] = client
    yield calls, answer
    app.dependency_overrides.clear()


def post(file_name="export.csv", content=CSV, user=ADMIN, **params):
    return TestClient(app).post("/v1/uploads", headers=auth(user), params=params,
                                files={"file": (file_name, content, "text/csv")})


def test_upload_is_forwarded(processing):
    calls, _ = processing
    r = post()
    assert r.status_code == 202 and r.json()["import_id"] == "abc"
    assert len(calls) == 1
    sent = calls[0]
    assert sent.url.path == "/imports" and sent.url.params["validate_only"] == "false"
    body = sent.read()
    assert b'filename="export.csv"' in body and CSV in body


def test_validate_only_returns_report(processing):
    calls, answer = processing
    answer.update(status=200, json={"status": "validated", "issues": []})
    r = post(validate_only="true")
    assert r.status_code == 200 and r.json()["status"] == "validated"
    assert calls[0].url.params["validate_only"] == "true"


def test_duplicate_file_is_409(processing):
    _, answer = processing
    answer.update(status=409, json={"detail": "already imported"})
    assert post().status_code == 409


def test_only_administrators_may_upload(processing):
    calls, _ = processing
    assert post(user=PARTICIPANT).status_code == 403
    assert TestClient(app).post("/v1/uploads", files={"file": ("a.csv", CSV)}).status_code == 401
    assert calls == []


@pytest.mark.parametrize("file_name, content, status", [
    ("export.xlsx", CSV, 415),
    ("export.csv", b"", 422),
])
def test_bad_files_are_refused_before_forwarding(processing, file_name, content, status):
    calls, _ = processing
    assert post(file_name, content).status_code == status
    assert calls == []


def test_too_large_file_is_413(processing, monkeypatch):
    calls, _ = processing
    monkeypatch.setattr(upload_handler.config, "MAX_UPLOAD_BYTES", 10)
    assert post().status_code == 413
    assert calls == []


def test_path_in_file_name_is_removed(processing):
    calls, _ = processing
    post(file_name="..\\..\\secret\\export.csv")
    assert b'filename="export.csv"' in calls[0].read()


@pytest.mark.parametrize("error, status", [
    (httpx.ConnectError("refused"), 503),
    (httpx.ReadTimeout("slow"), 504),
])
def test_processing_service_down(processing, error, status):
    _, answer = processing
    answer["error"] = error
    assert post().status_code == status


def test_processing_service_error_is_502(processing):
    _, answer = processing
    answer.update(status=500, json={"detail": "boom"})
    r = post()
    assert r.status_code == 502 and r.json()["detail"] == "boom"
