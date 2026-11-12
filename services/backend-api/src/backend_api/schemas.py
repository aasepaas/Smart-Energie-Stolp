"""Pydantic-modellen: valideren wat de services sturen en wat de API teruggeeft."""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from .config import MAX_BATCH

Kwh = Annotated[Decimal, Field(max_digits=10, decimal_places=3)]


def batch(item):
    """Lijst van 1 tot MAX_BATCH items."""
    return Annotated[list[item], Field(min_length=1, max_length=MAX_BATCH)]


# ---------- Meterdata ----------


class Meter(BaseModel):
    meter_reference: str
    participant_id: UUID | None


class NewMeters(BaseModel):
    meter_references: Annotated[
        list[Annotated[str, Field(max_length=20)]],
        Field(min_length=1, max_length=MAX_BATCH),
    ]


class Reading(BaseModel):
    meter_reference: Annotated[str, Field(max_length=20)]
    ts: AwareDatetime
    to_grid_kwh: Kwh
    from_grid_kwh: Kwh


class ImportStart(BaseModel):
    file_name: Annotated[str, Field(max_length=255)]
    file_hash: Annotated[
        str, Field(min_length=64, max_length=64, pattern="^[0-9a-f]{64}$")
    ]
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None


class ImportUpdate(BaseModel):
    status: Literal["running", "succeeded", "failed"] | None = None
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None
    row_count: int | None = None
    new_meter_count: int | None = None
    error_message: str | None = None


class ImportRecord(BaseModel):
    id: UUID
    file_name: str
    status: str
    row_count: int | None
    new_meter_count: int | None
    error_message: str | None
    started_at: datetime


# ---------- Resultaten ----------


class SimultaneityRow(BaseModel):
    ts: AwareDatetime
    total_to_grid_kwh: Kwh
    total_from_grid_kwh: Kwh
    shared_kwh: Kwh
    meter_count: int


class SimultaneityPeriod(BaseModel):
    """Vervangt alle rijen in [start, end) door de meegestuurde rijen."""

    start: AwareDatetime
    end: AwareDatetime
    rows: batch(SimultaneityRow)


class Forecast(BaseModel):
    participant_id: UUID
    ts: AwareDatetime
    run_date: date
    to_grid_p10: Kwh | None = None
    to_grid_p50: Kwh | None = None
    to_grid_p90: Kwh | None = None
    from_grid_p10: Kwh | None = None
    from_grid_p50: Kwh | None = None
    from_grid_p90: Kwh | None = None
    model_version: Annotated[str, Field(max_length=100)]


class EnergyPrice(BaseModel):
    ts: AwareDatetime
    price_eur_per_kwh: Annotated[Decimal, Field(max_digits=8, decimal_places=5)]


class AdviceItem(BaseModel):
    participant_id: UUID
    rank: Annotated[int, Field(ge=1, le=3)]
    appliance_category: Literal["transport", "heat_pump", "air_conditioning"]
    suggested_start: AwareDatetime
    suggested_end: AwareDatetime
    impact: Literal["high", "medium", "low"]
    expected_shared_kwh: Kwh
    acceptance_probability: (
        Annotated[Decimal, Field(ge=0, le=1, max_digits=4, decimal_places=3)] | None
    ) = None

    @model_validator(mode="after")
    def end_after_start(self):
        if self.suggested_end <= self.suggested_start:
            raise ValueError("suggested_end moet na suggested_start liggen")
        return self


class AdviceDay(BaseModel):
    """Het top-3-advies van één dag; vervangt eerder advies voor die dag."""

    advice_date: date
    items: batch(AdviceItem)


class Advice(AdviceItem):
    id: UUID
    advice_date: date
    feedback: str | None
    measured_effect_kwh: Decimal | None


class AdviceEffect(BaseModel):
    id: UUID
    measured_effect_kwh: Kwh


# ---------- Referentiedata ----------


class Participant(BaseModel):
    id: UUID
    name: str


class Appliance(BaseModel):
    id: UUID
    participant_id: UUID
    category: str
    power_kw: Decimal
    earliest_start: time
    latest_end: time
    min_run_minutes: int


class Setting(BaseModel):
    key: str
    value: dict | list | str | int | float | bool | None


class Count(BaseModel):
    count: int
