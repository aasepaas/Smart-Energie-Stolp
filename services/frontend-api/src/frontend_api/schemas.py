"""Pydantic models: validate what the web app sends and what the API returns.

Energy values are returned as numbers (float), which the web app can chart directly.
"""

from datetime import date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from . import config
from .authentication import Role

Bucket = Literal["quarter", "hour", "day", "month"]
ApplianceCategory = Literal["transport", "heat_pump", "air_conditioning"]
Feedback = Literal["accepted", "rejected"]

Email = Annotated[str, Field(max_length=255, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
NewPassword = Annotated[str, Field(min_length=config.MIN_PASSWORD_LENGTH, max_length=128)]


def _normalise_email(value: str | None) -> str | None:
    return value.strip().lower() if value is not None else None


# ---------- Authentication ----------


class LoginRequest(BaseModel):
    email: Annotated[str, Field(max_length=255)]
    password: Annotated[str, Field(max_length=128)]

    _email = field_validator("email")(_normalise_email)


class CurrentUser(BaseModel):
    id: UUID
    role: Role
    participant_id: UUID | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int  # seconds
    user: CurrentUser


# ---------- Energy data ----------


class ParticipantReading(BaseModel):
    participant_id: UUID
    ts: datetime
    to_grid_kwh: float
    from_grid_kwh: float
    shared_kwh: float | None
    quarter_count: int  # quarters with data in this bucket; fewer means gaps


class SimultaneityBucket(BaseModel):
    ts: datetime
    total_to_grid_kwh: float
    total_from_grid_kwh: float
    shared_kwh: float
    simultaneity: float | None  # shared / feed-in, None without feed-in
    meter_count: int
    quarter_count: int


class SimultaneityTotals(BaseModel):
    total_to_grid_kwh: float
    total_from_grid_kwh: float
    shared_kwh: float
    simultaneity: float | None
    quarter_count: int


class SimultaneityResponse(BaseModel):
    summary: SimultaneityTotals
    rows: list[SimultaneityBucket]


class Forecast(BaseModel):
    participant_id: UUID
    ts: datetime
    run_date: date
    to_grid_p10: float | None
    to_grid_p50: float | None
    to_grid_p90: float | None
    from_grid_p10: float | None
    from_grid_p50: float | None
    from_grid_p90: float | None
    model_version: str


class EnergyPrice(BaseModel):
    ts: datetime
    price_eur_per_kwh: float


# ---------- Advice ----------


class Advice(BaseModel):
    id: UUID
    participant_id: UUID
    advice_date: date
    rank: int
    appliance_category: ApplianceCategory
    suggested_start: datetime
    suggested_end: datetime
    impact: Literal["high", "medium", "low"]
    expected_shared_kwh: float
    feedback: Feedback | None
    measured_effect_kwh: float | None


class AdviceFeedback(BaseModel):
    feedback: Feedback | None  # None withdraws the feedback


# ---------- Appliances ----------

PowerKw = Annotated[Decimal, Field(gt=0, max_digits=6, decimal_places=2)]
RunMinutes = Annotated[int, Field(gt=0, le=1440)]


class Appliance(BaseModel):
    id: UUID
    participant_id: UUID
    category: ApplianceCategory
    power_kw: float
    earliest_start: time  # the comfort window may cross midnight
    latest_end: time
    min_run_minutes: int


class NewAppliance(BaseModel):
    participant_id: UUID
    category: ApplianceCategory
    power_kw: PowerKw
    earliest_start: time
    latest_end: time
    min_run_minutes: RunMinutes


class ComfortLimits(BaseModel):
    """Fields a participant may change; send only the fields that change."""

    power_kw: PowerKw | None = None
    earliest_start: time | None = None
    latest_end: time | None = None
    min_run_minutes: RunMinutes | None = None

    @model_validator(mode="after")
    def no_nulls(self):
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("Comfort limits cannot be empty")
        return self


# ---------- Participants and meters ----------

Name = Annotated[str, Field(min_length=1, max_length=100)]


class Participant(BaseModel):
    id: UUID
    name: str
    meter_references: list[str]


class ParticipantIn(BaseModel):
    name: Name

    @field_validator("name")
    @classmethod
    def strip(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name cannot be empty")
        return value.strip()


class Meter(BaseModel):
    meter_reference: str
    participant_id: UUID | None
    last_reading_at: datetime | None


class MeterLink(BaseModel):
    participant_id: UUID | None  # None unlinks the meter


# ---------- Imports ----------


class ImportRecord(BaseModel):
    id: UUID
    file_name: str
    status: Literal["running", "succeeded", "failed"]
    period_start: datetime | None
    period_end: datetime | None
    row_count: int | None
    new_meter_count: int | None
    error_message: str | None
    started_at: datetime


# ---------- Settings ----------

SETTING_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,99}$"


class Setting(BaseModel):
    key: str
    value: Any
    updated_at: datetime


class SettingValue(BaseModel):
    value: dict | list | str | int | float | bool


# ---------- Accounts ----------


class User(BaseModel):
    id: UUID
    email: str
    role: Role
    participant_id: UUID | None


class NewUser(BaseModel):
    email: Email
    password: NewPassword
    role: Role
    participant_id: UUID | None = None

    _email = field_validator("email")(_normalise_email)

    @model_validator(mode="after")
    def participant_matches_role(self):
        check_participant_for_role(self.role, self.participant_id)
        return self


class UserUpdate(BaseModel):
    """Send only the fields that change. participant_id null unlinks the account."""

    email: Email | None = None
    password: NewPassword | None = None
    role: Role | None = None
    participant_id: UUID | None = None

    _email = field_validator("email")(_normalise_email)

    @model_validator(mode="after")
    def no_null_values(self):
        for name in ("email", "password", "role"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"{name} cannot be empty")
        return self


def check_participant_for_role(role: str, participant_id: UUID | None) -> None:
    """A participant account must point to a participant, other accounts must not."""
    if role == "participant" and participant_id is None:
        raise ValueError("A participant account needs a participant_id")
    if role != "participant" and participant_id is not None:
        raise ValueError("Only a participant account can have a participant_id")
