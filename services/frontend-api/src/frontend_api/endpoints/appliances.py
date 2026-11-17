"""Flexible appliances and their comfort limits."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from .. import query_builder
from ..authentication import ADMINS, OWN_DATA, Principal, allow, participant_scope
from ..query_executor import Session, get_session
from ..schemas import Appliance, ComfortLimits, NewAppliance
from . import not_found

router = APIRouter(prefix="/appliances", tags=["appliances"])


@router.get("", response_model=list[Appliance])
def list_appliances(participant_id: UUID | None = None,
                    user: Principal = allow(*OWN_DATA),
                    db: Session = Depends(get_session, scope="function")):
    """Appliances with comfort limits: own for a participant, all for an administrator."""
    return query_builder.appliances(db, participant_scope(user, participant_id))


@router.post("", response_model=Appliance, status_code=201)
def create_appliance(body: NewAppliance, user: Principal = allow(*ADMINS),
                     db: Session = Depends(get_session, scope="function")):
    """Adds an appliance to a participant; one per category (else 409)."""
    return query_builder.create_appliance(db, body.model_dump())


@router.patch("/{appliance_id}", response_model=Appliance)
def update_comfort_limits(appliance_id: UUID, body: ComfortLimits,
                          user: Principal = allow(*OWN_DATA),
                          db: Session = Depends(get_session, scope="function")):
    """Changes the comfort limits; a participant only of their own appliances."""
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "No fields to update")
    row = query_builder.update_appliance(db, appliance_id, fields)
    if row is None:
        raise not_found("Appliance")
    return row


@router.delete("/{appliance_id}", status_code=204)
def delete_appliance(appliance_id: UUID, user: Principal = allow(*ADMINS),
                     db: Session = Depends(get_session, scope="function")):
    if not query_builder.delete_appliance(db, appliance_id):
        raise not_found("Appliance")
