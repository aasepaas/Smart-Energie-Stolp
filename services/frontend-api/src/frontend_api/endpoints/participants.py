"""Participants and the link between meters and participants (admin panel)."""

from uuid import UUID

from fastapi import APIRouter, Depends, Path

from .. import query_builder
from ..authentication import ADMINS, OWN_DATA, Principal, allow
from ..query_executor import Session, get_session
from ..schemas import Meter, MeterLink, Participant, ParticipantIn
from . import not_found

router = APIRouter(tags=["participants and meters"])


@router.get("/participants", response_model=list[Participant])
def list_participants(user: Principal = allow(*OWN_DATA),
                      db: Session = Depends(get_session, scope="function")):
    """All participants with their meters; a participant only sees themselves."""
    return query_builder.list_participants(db)


@router.post("/participants", response_model=Participant, status_code=201)
def create_participant(body: ParticipantIn, user: Principal = allow(*ADMINS),
                       db: Session = Depends(get_session, scope="function")):
    """Adds a participant; the name must be unique (else 409)."""
    return query_builder.create_participant(db, body.name)


@router.patch("/participants/{participant_id}", response_model=Participant)
def rename_participant(participant_id: UUID, body: ParticipantIn,
                       user: Principal = allow(*ADMINS),
                       db: Session = Depends(get_session, scope="function")):
    row = query_builder.rename_participant(db, participant_id, body.name)
    if row is None:
        raise not_found("Participant")
    return row


@router.delete("/participants/{participant_id}", status_code=204)
def delete_participant(participant_id: UUID, user: Principal = allow(*ADMINS),
                       db: Session = Depends(get_session, scope="function")):
    """Deletes the participant with their accounts, appliances, forecasts and advice.
    Their meters and readings stay, unlinked."""
    if not query_builder.delete_participant(db, participant_id):
        raise not_found("Participant")


@router.get("/meters", response_model=list[Meter])
def list_meters(unlinked: bool = False, user: Principal = allow(*OWN_DATA),
                db: Session = Depends(get_session, scope="function")):
    """Meters with linked participant and last reading; `unlinked=true` only shows meters
    that still need a participant. A participant only sees their own meters."""
    return query_builder.list_meters(db, unlinked)


@router.put("/meters/{meter_reference}/participant", response_model=Meter)
def link_meter(body: MeterLink,
               meter_reference: str = Path(max_length=64),
               user: Principal = allow(*ADMINS),
               db: Session = Depends(get_session, scope="function")):
    """Links a meter to a participant, or unlinks it with participant_id null."""
    row = query_builder.link_meter(db, meter_reference, body.participant_id)
    if row is None:
        raise not_found("Meter")
    return row
