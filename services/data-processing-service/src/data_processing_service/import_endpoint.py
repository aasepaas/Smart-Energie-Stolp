"""Import endpoint (component 'Import endpoint' in C4 3.3).

    POST /imports                 Upload a CSV (multipart, field "file"). Registers the import
                                  in import_log and processes it in the background -> 202 + import_id.
    POST /imports?validate_only=true
                                  Only check, store nothing -> 200 + report.
    GET  /imports/{import_id}     Status and import report.
    GET  /health                  Check for Docker, without a token.

Only the Frontend API calls /imports, with `Authorization: Bearer <SES_TOKEN_FRONTEND>`.

Start:  uvicorn data_processing_service.import_endpoint:app --host 0.0.0.0 --port 8000
Docs:   http://localhost:8000/docs
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import (BackgroundTasks, Depends, FastAPI, File, HTTPException, Query,
                     UploadFile)
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import backend_client, config
from .backend_client import BackendClient, BackendError
from .import_orchestrator import process_import, register_import, run_import
from .models import ImportReport

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # well above one year of exports of the Stolp


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not config.FRONTEND_TOKEN:
        raise RuntimeError("Service token missing: set SES_TOKEN_FRONTEND")
    yield


app = FastAPI(title="SES Data processing service", version="0.1.0", lifespan=lifespan,
              description="Imports meter data (CSV export of the grid operator) and validates it.")

# Reports of this session, including issues. Status and counts are also in import_log.
_reports: dict[str, ImportReport] = {}

bearer = HTTPBearer(auto_error=False)


def frontend_only(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> None:
    """Only the Frontend API may start imports (service token, 401 otherwise)."""
    token = config.FRONTEND_TOKEN
    if (credentials is None or not token
            or not secrets.compare_digest(credentials.credentials, token)):
        raise HTTPException(401, "Missing or unknown service token")


@app.get("/health", tags=["status"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/imports", tags=["imports"], status_code=202, dependencies=[Depends(frontend_only)])
async def create_import(background: BackgroundTasks, file: UploadFile = File(...),
                        validate_only: bool = Query(False)):
    content = await file.read()
    name = file.filename or "upload.csv"
    if not name.lower().endswith(".csv"):
        raise HTTPException(415, "Only .csv files are accepted")
    if not content:
        raise HTTPException(422, "The file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "The file is too large")

    if validate_only:
        return JSONResponse(run_import(content, name, backend=None).to_dict(), status_code=200)

    try:
        backend = backend_client.create_backend()
    except BackendError as exc:
        raise HTTPException(503, str(exc)) from exc
    report = register_import(content, name, backend)
    if report.status == "duplicate":
        backend.close()
        raise HTTPException(409, report.error_message)
    if report.status == "failed":
        backend.close()
        raise HTTPException(502, report.error_message)
    _reports[report.import_id] = report
    background.add_task(_process, report, content, backend)
    return {"import_id": report.import_id, "status": report.status, "file_name": name}


@app.get("/imports/{import_id}", tags=["imports"], dependencies=[Depends(frontend_only)])
def get_import(import_id: str):
    report = _reports.get(import_id)
    if report is None:
        raise HTTPException(404, "Import not found")
    return report.to_dict()


def _process(report: ImportReport, content: bytes, backend: BackendClient) -> None:
    try:
        process_import(report, content, backend)
    finally:
        backend.close()
