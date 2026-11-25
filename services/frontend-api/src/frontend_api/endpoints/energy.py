"""Readings, simultaneity, forecasts and dynamic prices (data view of the web app)."""

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import AwareDatetime

from .. import query_builder
from ..authentication import EVERYONE, OWN_DATA, Principal, allow, participant_scope
from ..query_executor import Session, get_session
from ..schemas import (Bucket, EnergyPrice, Forecast, ParticipantReading, SimultaneityResponse,
                       SimultaneityTotals)
from . import check_period

router = APIRouter(tags=["energy data"])


@router.get("/readings", response_model=list[ParticipantReading])
def readings(start: AwareDatetime, end: AwareDatetime, bucket: Bucket = "quarter",
             participant_id: UUID | None = None,
             user: Principal = allow(*OWN_DATA),
             db: Session = Depends(get_session, scope="function")):
    """Consumption, feed-in and share of shared energy per participant in [start, end).

    A participant only gets their own data; an administrator gets all participants or
    the one in `participant_id`. Days and months follow Dutch local time.
    """
    check_period(start, end)
    scope = participant_scope(user, participant_id)
    return query_builder.participant_readings(db, start, end, bucket, scope)


@router.get("/simultaneity", response_model=SimultaneityResponse)
def simultaneity(start: AwareDatetime, end: AwareDatetime, bucket: Bucket = "quarter",
                 user: Principal = allow(*EVERYONE),
                 db: Session = Depends(get_session, scope="function")):
    """Simultaneity of the whole community in [start, end), with totals for the period.

    simultaneity = shared energy / feed-in (the KPI in CONTEXT.md).
    """
    check_period(start, end)
    rows = query_builder.community_simultaneity(db, start, end, bucket)
    to_grid = sum(float(r["total_to_grid_kwh"]) for r in rows)
    shared = sum(float(r["shared_kwh"]) for r in rows)
    summary = SimultaneityTotals(
        total_to_grid_kwh=round(to_grid, 3),
        total_from_grid_kwh=round(sum(float(r["total_from_grid_kwh"]) for r in rows), 3),
        shared_kwh=round(shared, 3),
        simultaneity=round(shared / to_grid, 4) if to_grid else None,
        quarter_count=sum(r["quarter_count"] for r in rows),
    )
    return {"summary": summary, "rows": rows}


@router.get("/forecasts", response_model=list[Forecast])
def forecasts(start: AwareDatetime, end: AwareDatetime, participant_id: UUID | None = None,
              user: Principal = allow(*OWN_DATA),
              db: Session = Depends(get_session, scope="function")):
    """Most recent P10/P50/P90 forecast of consumption and feed-in per quarter hour."""
    check_period(start, end)
    return query_builder.forecasts(db, start, end, participant_scope(user, participant_id))


@router.get("/prices", response_model=list[EnergyPrice])
def prices(start: AwareDatetime, end: AwareDatetime,
           user: Principal = allow(*EVERYONE),
           db: Session = Depends(get_session, scope="function")):
    """Dynamic day-ahead prices per quarter hour in [start, end)."""
    check_period(start, end)
    return query_builder.energy_prices(db, start, end)
