"""Authentication (component 'Authentication' in C4 3.2).

Logs users in, issues and verifies JWTs, and checks whether the role and owner of a
request may access the requested data. This is the first check; the database checks
again with GRANTs and row-level security (see query_executor.py).

Tokens:
    access token   short lived, sent by the web app as `Authorization: Bearer <token>`
    refresh token  long lived, only in an HttpOnly cookie, used by POST /v1/auth/refresh
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import config

Role = Literal["participant", "viewer", "administrator", "superadmin"]
ROLES: tuple[Role, ...] = ("participant", "viewer", "administrator", "superadmin")

# Application role -> database role (database/roles/readme.md)
DB_ROLES: dict[str, str] = {
    "participant": "web_participant",
    "viewer": "web_participant",  # without a linked participant: only community data
    "administrator": "web_admin",
    "superadmin": "web_admin",
}

# Groups used by the endpoints, after the permission matrix in database/roles/readme.md
EVERYONE: tuple[Role, ...] = ROLES
PARTICIPANT: tuple[Role, ...] = ("participant",)
ADMINS: tuple[Role, ...] = ("administrator", "superadmin")
OWN_DATA: tuple[Role, ...] = ("participant", "administrator", "superadmin")

_hasher = PasswordHasher()
# Verified when the email address is unknown, so a login takes as long either way
_DUMMY_HASH = _hasher.hash("not a real password")

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class Principal:
    """The logged in user of a request, taken from the access token."""

    user_id: UUID
    role: Role
    participant_id: UUID | None

    @property
    def db_role(self) -> str:
        return DB_ROLES[self.role]

    @property
    def is_admin(self) -> bool:
        return self.role in ADMINS


# ---------- Passwords ----------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    """True if the password matches. Without a hash (unknown user) always False."""
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


# ---------- Tokens ----------


def _encode(claims: dict, lifetime: timedelta) -> str:
    now = datetime.now(UTC)
    payload = {**claims, "iss": config.JWT_ISSUER, "iat": now, "exp": now + lifetime}
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def _decode(token: str, token_type: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=["HS256"],
            issuer=config.JWT_ISSUER,
            options={"require": ["exp", "iat", "iss", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid token") from exc
    if claims["typ"] != token_type:
        raise _unauthorized("Invalid token")
    return claims


def create_access_token(user: Principal) -> str:
    return _encode(
        {
            "typ": "access",
            "sub": str(user.user_id),
            "role": user.role,
            "pid": str(user.participant_id) if user.participant_id else None,
        },
        timedelta(minutes=config.ACCESS_TOKEN_MINUTES),
    )


def create_refresh_token(user_id: UUID, email: str) -> str:
    """The email address is used on refresh to load the account (and its current role) again."""
    return _encode(
        {"typ": "refresh", "sub": str(user_id), "email": email},
        timedelta(hours=config.REFRESH_TOKEN_HOURS),
    )


def decode_refresh_token(token: str) -> tuple[UUID, str]:
    claims = _decode(token, "refresh")
    try:
        return UUID(claims["sub"]), str(claims["email"])
    except (KeyError, ValueError) as exc:
        raise _unauthorized("Invalid token") from exc


def principal(user_id: UUID, role: str, participant_id: UUID | None) -> Principal:
    """Builds a Principal from an account; refuses roles this API does not know."""
    if role not in ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Unknown role '{role}'")
    if (role == "participant") != (participant_id is not None):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is not configured correctly")
    return Principal(user_id, role, participant_id)


# ---------- Dependencies ----------


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> Principal:
    """The user from the access token; 401 without a valid token."""
    if credentials is None:
        raise _unauthorized("Access token missing")
    claims = _decode(credentials.credentials, "access")
    try:
        user_id = UUID(claims["sub"])
        participant_id = UUID(claims["pid"]) if claims.get("pid") else None
        role = claims["role"]
    except (KeyError, ValueError, TypeError) as exc:
        raise _unauthorized("Invalid token") from exc
    if role not in ROLES:
        raise _unauthorized("Invalid token")
    return Principal(user_id, role, participant_id)


def allow(*roles: Role):
    """Route dependency: only users with one of these roles may use the endpoint (else 403).

    Returns the Principal, so an endpoint can use `user: Principal = allow(...)`.
    """

    def check(user: Principal = Depends(current_user)) -> Principal:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Role '{user.role}' may not use this endpoint"
            )
        return user

    return Depends(check)


# ---------- Ownership ----------


def participant_scope(user: Principal, requested: UUID | None) -> UUID | None:
    """Which participant's data a request may see.

    A participant only sees their own data: no filter means their own, another id is 403.
    An administrator sees everyone: no filter (None) means all participants.
    """
    if user.role == "participant":
        if requested is not None and requested != user.participant_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only your own data is available")
        return user.participant_id
    if user.is_admin:
        return requested
    raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to participant data")


def check_account_management(user: Principal, *roles_involved: str) -> None:
    """An administrator manages participant and viewer accounts; only a superadmin
    may create, change or delete administrator and superadmin accounts."""
    if user.role == "superadmin":
        return
    if any(role in ADMINS for role in roles_involved):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only a superadmin can manage administrator accounts"
        )


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )
