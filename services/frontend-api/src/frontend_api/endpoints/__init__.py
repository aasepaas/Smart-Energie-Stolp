"""API endpoints (component 'API endpoints' in C4 3.2): one router per resource."""

from datetime import date, datetime, timedelta

from fastapi import HTTPException

from .. import config


def check_period(start: datetime | date, end: datetime | date) -> None:
    """end must be after start, and the period may not exceed MAX_PERIOD_DAYS (else 422)."""
    if end < start or (isinstance(start, datetime) and end == start):
        raise HTTPException(422, "end must be after start")
    if end - start > timedelta(days=config.MAX_PERIOD_DAYS):
        raise HTTPException(422, f"The period may be at most {config.MAX_PERIOD_DAYS} days")


def not_found(what: str) -> HTTPException:
    return HTTPException(404, f"{what} not found")
