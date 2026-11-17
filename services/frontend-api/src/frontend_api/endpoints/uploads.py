"""CSV uploads of meter data (administrators only)."""

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse

from .. import query_builder, upload_handler
from ..authentication import ADMINS, Principal, allow
from ..query_executor import Session, get_session
from ..schemas import ImportRecord
from . import not_found

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", status_code=202, responses={
    200: {"description": "validate_only: validation report, nothing stored"},
    409: {"description": "This file was imported before"},
})
def upload_csv(file: UploadFile = File(...), validate_only: bool = False,
               user: Principal = allow(*ADMINS),
               client: httpx.Client = Depends(upload_handler.get_processing_client)):
    """Forwards a CSV export of the grid operator to the data processing service.

    202 with `import_id`: the import runs in the background, follow it with
    GET /v1/uploads/{import_id}.
    """
    name = upload_handler.check_upload(file)
    status_code, body = upload_handler.forward_upload(client, file, name, validate_only)
    return JSONResponse(body, status_code=status_code)


@router.get("", response_model=list[ImportRecord])
def list_uploads(limit: int = Query(50, ge=1, le=500), user: Principal = allow(*ADMINS),
                 db: Session = Depends(get_session, scope="function")):
    """Most recent imports with status and result (import_log)."""
    return query_builder.list_imports(db, limit)


@router.get("/{import_id}", response_model=ImportRecord)
def get_upload(import_id: UUID, user: Principal = allow(*ADMINS),
               db: Session = Depends(get_session, scope="function")):
    """Status and result of one import."""
    row = query_builder.get_import(db, import_id)
    if row is None:
        raise not_found("Import")
    return row
