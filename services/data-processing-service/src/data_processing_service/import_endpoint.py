"""Import endpoint (component 'Import endpoint' in C4 3.3).

    POST /imports                 CSV uploaden (multipart, veld "file"). Registreert de import
                                  in import_log en verwerkt op de achtergrond -> 202 + import_id.
    POST /imports?validate_only=true
                                  Alleen controleren, niets wegschrijven -> 200 + rapport.
    GET  /imports/{import_id}     Status en importrapport.
    GET  /health                  Controle voor Docker.

Start:  uvicorn data_processing_service.import_endpoint:app --host 0.0.0.0 --port 8000
Docs:   http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from . import backend_client
from .backend_client import BackendClient, BackendError
from .import_orchestrator import process_import, register_import, run_import
from .models import ImportReport

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # ruim boven een jaarexport van de Stolp

app = FastAPI(title="SES Data processing service", version="0.1.0",
              description="Importeert meterdata (CSV van de netbeheerder) en valideert die.")

# Rapporten van deze sessie, inclusief meldingen. Status en aantallen staan ook in import_log.
_reports: dict[str, ImportReport] = {}


@app.get("/health", tags=["status"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/imports", tags=["imports"], status_code=202)
async def create_import(background: BackgroundTasks, file: UploadFile = File(...),
                        validate_only: bool = Query(False)):
    content = await file.read()
    name = file.filename or "upload.csv"
    if not name.lower().endswith(".csv"):
        raise HTTPException(415, "alleen .csv-bestanden")
    if not content:
        raise HTTPException(422, "het bestand is leeg")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "het bestand is te groot")

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


@app.get("/imports/{import_id}", tags=["imports"])
def get_import(import_id: str):
    report = _reports.get(import_id)
    if report is None:
        raise HTTPException(404, "import niet gevonden")
    return report.to_dict()


def _process(report: ImportReport, content: bytes, backend: BackendClient) -> None:
    try:
        process_import(report, content, backend)
    finally:
        backend.close()
