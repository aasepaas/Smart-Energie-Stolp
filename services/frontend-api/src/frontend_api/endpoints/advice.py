"""Personal advice and feedback."""

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends

from .. import query_builder
from ..authentication import OWN_DATA, PARTICIPANT, Principal, allow, participant_scope
from ..query_executor import Session, get_session
from ..schemas import Advice, AdviceFeedback
from . import check_period, not_found

router = APIRouter(prefix="/advice", tags=["advice"])


@router.get("", response_model=list[Advice])
def list_advice(start_date: date, end_date: date, participant_id: UUID | None = None,
                user: Principal = allow(*OWN_DATA),
                db: Session = Depends(get_session, scope="function")):
    """Top 3 advice per day in [start_date, end_date], with feedback and measured effect."""
    check_period(start_date, end_date)
    return query_builder.advice(db, start_date, end_date, participant_scope(user, participant_id))


@router.put("/{advice_id}/feedback", response_model=Advice)
def give_feedback(advice_id: UUID, body: AdviceFeedback,
                  user: Principal = allow(*PARTICIPANT),
                  db: Session = Depends(get_session, scope="function")):
    """A participant accepts or rejects one of their own advice (null withdraws it)."""
    row = query_builder.set_advice_feedback(db, advice_id, body.feedback)
    if row is None:  # does not exist, or belongs to someone else (row-level security)
        raise not_found("Advice")
    return row
