"""Upload handler (component 'Upload handler' in C4 3.2).

Checks file type and size of a CSV upload and forwards it to the Data processing
service (POST /imports, multipart). The processing service parses, validates and
imports the file; its answer is passed on to the web app:

    202  import started, poll GET /v1/uploads/{import_id}
    200  validate_only: the validation report, nothing stored
    409  the same file was imported before
    413, 415, 422  refused by the processing service
"""

from collections.abc import Iterator
from pathlib import PurePath
from typing import Any

import httpx
from fastapi import HTTPException, UploadFile, status

from . import config


def get_processing_client() -> Iterator[httpx.Client]:
    """HTTP client for the Data processing service (replaced in the tests)."""
    with httpx.Client(base_url=config.PROCESSING_SERVICE_URL,
                      timeout=config.PROCESSING_TIMEOUT) as client:
        yield client


def file_name(upload: UploadFile) -> str:
    """Only the base name, no path from the client, at most 255 characters (import_log)."""
    name = PurePath((upload.filename or "").replace("\\", "/")).name
    return name[-255:] or "upload.csv"


def check_upload(upload: UploadFile) -> str:
    """Checks extension and size before anything is forwarded; returns the file name."""
    name = file_name(upload)
    if not name.lower().endswith(".csv"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only .csv files are accepted")
    size = upload.size
    if size is None:
        upload.file.seek(0, 2)
        size = upload.file.tell()
    if size == 0:
        raise HTTPException(422, "The file is empty")
    if size > config.MAX_UPLOAD_BYTES:
        raise HTTPException(
            413,
            f"The file is larger than {config.MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    return name


def forward_upload(client: httpx.Client, upload: UploadFile, name: str,
                   validate_only: bool) -> tuple[int, Any]:
    """Streams the file to the processing service; returns its status code and body."""
    upload.file.seek(0)
    try:
        response = client.post(
            "/imports",
            params={"validate_only": "true" if validate_only else "false"},
            files={"file": (name, upload.file, "text/csv")},
        )
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status.HTTP_504_GATEWAY_TIMEOUT, "The data processing service did not answer in time"
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "The data processing service is not reachable"
        ) from exc

    try:
        body = response.json()
    except ValueError:
        body = {"detail": response.text[:500]}
    if response.status_code >= 500:
        detail = body.get("detail") if isinstance(body, dict) else None
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            detail or "The data processing service failed")
    return response.status_code, body
