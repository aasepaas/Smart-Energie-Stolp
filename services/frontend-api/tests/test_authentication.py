"""Unit tests of the authentication component (no database needed)."""

import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from frontend_api import authentication
from frontend_api.authentication import Principal

PARTICIPANT = Principal(uuid.uuid4(), "participant", uuid.uuid4())
VIEWER = Principal(uuid.uuid4(), "viewer", None)
ADMIN = Principal(uuid.uuid4(), "administrator", None)
SUPERADMIN = Principal(uuid.uuid4(), "superadmin", None)


def bearer(token: str) -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)


def test_password_hash_and_verify():
    hashed = authentication.hash_password("correct horse battery")
    assert hashed.startswith("$argon2")
    assert authentication.verify_password(hashed, "correct horse battery")
    assert not authentication.verify_password(hashed, "wrong password")
    assert not authentication.verify_password(None, "anything")
    assert not authentication.verify_password("not-a-hash", "anything")


@pytest.mark.parametrize("user", [PARTICIPANT, VIEWER, ADMIN, SUPERADMIN])
def test_access_token_round_trip(user):
    token = authentication.create_access_token(user)
    assert authentication.current_user(bearer(token)) == user


def test_db_roles():
    assert PARTICIPANT.db_role == VIEWER.db_role == "web_participant"
    assert ADMIN.db_role == SUPERADMIN.db_role == "web_admin"


def test_missing_expired_or_tampered_token_is_401(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        authentication.current_user(None)
    assert exc.value.status_code == 401

    token = authentication.create_access_token(ADMIN)
    with pytest.raises(HTTPException) as exc:
        authentication.current_user(bearer(token[:-2] + "xx"))
    assert exc.value.status_code == 401

    monkeypatch.setattr(authentication.config, "ACCESS_TOKEN_MINUTES", -1)
    expired = authentication.create_access_token(ADMIN)
    with pytest.raises(HTTPException) as exc:
        authentication.current_user(bearer(expired))
    assert exc.value.detail == "Token expired"


def test_refresh_token_is_not_an_access_token():
    refresh = authentication.create_refresh_token(ADMIN.user_id, "admin@example.org")
    with pytest.raises(HTTPException):
        authentication.current_user(bearer(refresh))
    assert authentication.decode_refresh_token(refresh) == (ADMIN.user_id, "admin@example.org")
    with pytest.raises(HTTPException):
        authentication.decode_refresh_token(authentication.create_access_token(ADMIN))


def test_token_signed_with_other_secret_is_401(monkeypatch):
    monkeypatch.setattr(authentication.config, "JWT_SECRET", "x" * 40)
    token = authentication.create_access_token(ADMIN)
    monkeypatch.undo()
    with pytest.raises(HTTPException):
        authentication.current_user(bearer(token))


def test_participant_scope():
    own = PARTICIPANT.participant_id
    assert authentication.participant_scope(PARTICIPANT, None) == own
    assert authentication.participant_scope(PARTICIPANT, own) == own
    with pytest.raises(HTTPException) as exc:
        authentication.participant_scope(PARTICIPANT, uuid.uuid4())
    assert exc.value.status_code == 403

    other = uuid.uuid4()
    assert authentication.participant_scope(ADMIN, None) is None
    assert authentication.participant_scope(SUPERADMIN, other) == other
    with pytest.raises(HTTPException):
        authentication.participant_scope(VIEWER, None)


def test_account_management():
    authentication.check_account_management(ADMIN, "participant", "viewer")
    for role in ("administrator", "superadmin"):
        with pytest.raises(HTTPException) as exc:
            authentication.check_account_management(ADMIN, "participant", role)
        assert exc.value.status_code == 403
        authentication.check_account_management(SUPERADMIN, role)


def test_principal_checks_account():
    pid = uuid.uuid4()
    assert authentication.principal(PARTICIPANT.user_id, "participant", pid).participant_id == pid
    with pytest.raises(HTTPException):
        authentication.principal(uuid.uuid4(), "participant", None)
    with pytest.raises(HTTPException):
        authentication.principal(uuid.uuid4(), "administrator", pid)
    with pytest.raises(HTTPException):
        authentication.principal(uuid.uuid4(), "root", None)


def test_access_token_lifetime(monkeypatch):
    import jwt

    token = authentication.create_access_token(ADMIN)
    claims = jwt.decode(token, options={"verify_signature": False})
    lifetime = timedelta(seconds=claims["exp"] - claims["iat"])
    assert lifetime == timedelta(minutes=authentication.config.ACCESS_TOKEN_MINUTES)
    assert claims["typ"] == "access" and claims["role"] == "administrator"
