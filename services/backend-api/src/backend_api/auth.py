"""Authentication for the backend-services with a service token.

Each service sends an `Authorization: Bearer <token>` along. The token decides
which service it is and which database role it translates to.
"""

import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import SERVICE_TOKENS

# Service -> databaserol uit rollen_en_rechten.sql
DB_ROLES = {
    "processing": "svc_processing",
    "training": "svc_training",
    "forecast": "svc_forecast",
}

#get tghe token out of the http request, none if there is no token
bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Service:
    name: str
    db_role: str


def current_service(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Service:
    """Checks which services is making the request; 401 if no or unknown token."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Service token missing")
    for name, token in SERVICE_TOKENS.items():
        # compare_digest prevents that the token is visible during runtime
        if token and secrets.compare_digest(credentials.credentials, token):
            return Service(name, DB_ROLES[name])
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "unknown service token")


def allow(*services: str):
    """Route-dependency: checks if the endpoint is reachable with the token from the requst.

    This is the first control moment; the database does the second control moment. if a request
    goes through the database checks again for security reasons
    """
    def check(service: Service = Depends(current_service)) -> Service:
        if service.name not in services:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Service '{service.name}' may not use this endpoint",
            )
        return service

    return Depends(check)
