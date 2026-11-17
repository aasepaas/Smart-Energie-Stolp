"""Accounts: administrators manage participant and viewer accounts,
a superadmin also manages administrator and superadmin accounts."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from .. import authentication, query_builder
from ..authentication import ADMINS, Principal, allow, check_account_management
from ..query_executor import Session, get_session
from ..schemas import NewUser, User, UserUpdate, check_participant_for_role
from . import not_found

router = APIRouter(prefix="/users", tags=["accounts"])


@router.get("", response_model=list[User])
def list_users(user: Principal = allow(*ADMINS),
               db: Session = Depends(get_session, scope="function")):
    return query_builder.list_users(db)


@router.post("", response_model=User, status_code=201)
def create_user(body: NewUser, user: Principal = allow(*ADMINS),
                db: Session = Depends(get_session, scope="function")):
    """Creates an account; the email address must be unique (else 409)."""
    check_account_management(user, body.role)
    return query_builder.create_user(
        db, body.email, authentication.hash_password(body.password), body.role, body.participant_id
    )


@router.patch("/{user_id}", response_model=User)
def update_user(user_id: UUID, body: UserUpdate, user: Principal = allow(*ADMINS),
                db: Session = Depends(get_session, scope="function")):
    """Changes email, password, role or linked participant of an account."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "No fields to update")
    current = query_builder.get_user(db, user_id)
    if current is None:
        raise not_found("Account")
    new_role = changes.get("role", current["role"])
    check_account_management(user, current["role"], new_role)
    if user_id == user.user_id and new_role != current["role"]:
        raise HTTPException(409, "You cannot change your own role")
    try:
        new_participant = changes.get("participant_id", current["participant_id"])
        check_participant_for_role(new_role, new_participant)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    if "password" in changes:
        changes["password_hash"] = authentication.hash_password(changes.pop("password"))
    return query_builder.update_user(db, user_id, changes)


@router.delete("/{user_id}", status_code=204)
def delete_user(user_id: UUID, user: Principal = allow(*ADMINS),
                db: Session = Depends(get_session, scope="function")):
    if user_id == user.user_id:
        raise HTTPException(409, "You cannot delete your own account")
    current = query_builder.get_user(db, user_id)
    if current is None:
        raise not_found("Account")
    check_account_management(user, current["role"])
    query_builder.delete_user(db, user_id)
