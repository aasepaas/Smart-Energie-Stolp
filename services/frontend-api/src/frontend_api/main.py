"""SES Frontend API: the single entry point for the web app.

Start:  uvicorn frontend_api.main:app --host 0.0.0.0 --port 8002
Docs:   http://localhost:8002/docs
"""

from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import config
from .endpoints import advice, appliances, auth, energy, participants, settings, uploads, users
from .query_executor import pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    if len(config.JWT_SECRET) < 32:
        raise RuntimeError("SES_JWT_SECRET is missing or shorter than 32 characters")
    if not config.PROCESSING_SERVICE_TOKEN:
        raise RuntimeError("Service token for the data processing service missing: "
                           "set SES_TOKEN_FRONTEND")
    pool.open()
    yield
    pool.close()


app = FastAPI(
    title="SES Frontend API",
    description="Single entry point for the Smart Energie Stolp web app. Log in with "
    "POST /v1/auth/login and send the access token as `Authorization: Bearer <token>`.",
    version="1.0.0",
    lifespan=lifespan,
)

if config.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_credentials=True,  # the refresh cookie
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

for router in (auth, energy, advice, appliances, participants, uploads, settings, users):
    app.include_router(router.router, prefix="/v1")


@app.get("/health", tags=["status"])
def health():
    """Check for Docker: the API is running and the database is reachable."""
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


# ---------- Database errors translated to HTTP responses ----------


@app.exception_handler(psycopg.errors.InsufficientPrivilege)
def no_privilege(request: Request, exc: psycopg.Error):
    # the database refuses an action for this role, which the API let through
    return JSONResponse(status_code=403,
                        content={"detail": "The database refuses the action for this role"})


@app.exception_handler(psycopg.errors.UniqueViolation)
def duplicate(request: Request, exc: psycopg.Error):
    return JSONResponse(status_code=409, content={
        "detail": "Already exists", "constraint": exc.diag.constraint_name})


@app.exception_handler(psycopg.errors.ForeignKeyViolation)
def missing_reference(request: Request, exc: psycopg.Error):
    return JSONResponse(status_code=422, content={
        "detail": "Referenced item does not exist", "constraint": exc.diag.constraint_name})


@app.exception_handler(psycopg.errors.CheckViolation)
def check_failed(request: Request, exc: psycopg.Error):
    return JSONResponse(status_code=422, content={
        "detail": "Value violates a check constraint in the database",
        "constraint": exc.diag.constraint_name})


@app.exception_handler(psycopg.errors.DataError)
def invalid_value(request: Request, exc: psycopg.Error):
    # for example a role the database enum does not know yet
    return JSONResponse(status_code=422,
                        content={"detail": "Value is not accepted by the database"})
