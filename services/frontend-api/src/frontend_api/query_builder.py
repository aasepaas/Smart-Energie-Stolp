"""Query builder (component 'Query builder' in C4 3.2).

Translates a request into a parameterised query and runs it through the query
executor. All SQL of the Frontend API is in this module. Values are always passed
as parameters; identifiers only come from fixed lists in this module or from
Pydantic models (via psycopg.sql), never from user input.

`participant_id` arguments come from authentication.participant_scope: a participant
always gets their own id, an administrator gets the requested id or None (everyone).
Row-level security in the database applies the same limit a second time.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from . import config
from .query_executor import Session

BUCKETS = {"quarter": "15 minutes", "hour": "1 hour", "day": "1 day", "month": "1 month"}


def _participant_filter(column: str, participant_id: UUID | None, params: dict) -> str:
    if participant_id is None:
        return ""
    params["participant_id"] = participant_id
    return f" AND {column} = %(participant_id)s"


def _update(table: str, fields: Mapping[str, Any], key_column: str, key: Any,
            returning: str) -> sql.Composed:
    """UPDATE <table> SET <fields> WHERE <key_column> = key RETURNING ...

    `table`, `key_column` and `returning` are constants from this module; the field
    names come from a Pydantic model and are quoted as identifiers.
    """
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(name), sql.Placeholder(name)) for name in fields
    )
    return sql.SQL("UPDATE {} SET {} WHERE {} = {} RETURNING {}").format(
        sql.Identifier(table), assignments, sql.Identifier(key_column),
        sql.Placeholder("_key"), sql.SQL(returning),
    )


# ---------- Accounts and login ----------


def account_by_email(db: Session, email: str) -> dict | None:
    """Account with password hash, through the SECURITY DEFINER function (login only)."""
    return db.one(
        "SELECT user_id, password_hash, user_role::text AS role, participant_id "
        "FROM auth_user_by_email(%s)",
        [email],
    )


USER_COLUMNS = "id, email, role::text AS role, participant_id"


def list_users(db: Session) -> list[dict]:
    return db.all(f"SELECT {USER_COLUMNS} FROM users ORDER BY email")


def get_user(db: Session, user_id: UUID) -> dict | None:
    return db.one(f"SELECT {USER_COLUMNS} FROM users WHERE id = %s", [user_id])


def create_user(db: Session, email: str, password_hash: str, role: str,
                participant_id: UUID | None) -> dict:
    return db.one(
        "INSERT INTO users (email, password_hash, role, participant_id) "
        f"VALUES (%s, %s, %s, %s) RETURNING {USER_COLUMNS}",
        [email, password_hash, role, participant_id],
    )


def update_user(db: Session, user_id: UUID, fields: Mapping[str, Any]) -> dict | None:
    query = _update("users", fields, "id", user_id, USER_COLUMNS)
    return db.one(query, {**fields, "_key": user_id})


def delete_user(db: Session, user_id: UUID) -> int:
    return db.execute("DELETE FROM users WHERE id = %s", [user_id])


# ---------- Participants and meters ----------

PARTICIPANT_QUERY = (
    "SELECT p.id, p.name, "
    "COALESCE(array_agg(m.meter_reference ORDER BY m.meter_reference) "
    "FILTER (WHERE m.meter_reference IS NOT NULL), '{}') AS meter_references "
    "FROM participants p LEFT JOIN meters m ON m.participant_id = p.id "
)


def list_participants(db: Session) -> list[dict]:
    return db.all(PARTICIPANT_QUERY + "GROUP BY p.id ORDER BY p.name")


def get_participant(db: Session, participant_id: UUID) -> dict | None:
    return db.one(PARTICIPANT_QUERY + "WHERE p.id = %s GROUP BY p.id", [participant_id])


def create_participant(db: Session, name: str) -> dict:
    row = db.one("INSERT INTO participants (name) VALUES (%s) RETURNING id", [name])
    return get_participant(db, row["id"])


def rename_participant(db: Session, participant_id: UUID, name: str) -> dict | None:
    if not db.execute("UPDATE participants SET name = %s WHERE id = %s", [name, participant_id]):
        return None
    return get_participant(db, participant_id)


def delete_participant(db: Session, participant_id: UUID) -> int:
    """Also deletes accounts, appliances, forecasts and advice; meters become unlinked."""
    return db.execute("DELETE FROM participants WHERE id = %s", [participant_id])


METER_QUERY = (
    "SELECT m.meter_reference, m.participant_id, "
    "(SELECT max(r.ts) FROM readings r WHERE r.meter_reference = m.meter_reference) "
    "AS last_reading_at FROM meters m "
)


def list_meters(db: Session, unlinked_only: bool) -> list[dict]:
    where = "WHERE m.participant_id IS NULL " if unlinked_only else ""
    return db.all(METER_QUERY + where + "ORDER BY m.meter_reference")


def link_meter(db: Session, meter_reference: str, participant_id: UUID | None) -> dict | None:
    if not db.execute("UPDATE meters SET participant_id = %s WHERE meter_reference = %s",
                      [participant_id, meter_reference]):
        return None
    return db.one(METER_QUERY + "WHERE m.meter_reference = %s", [meter_reference])


# ---------- Energy data ----------


def participant_readings(db: Session, start: datetime, end: datetime, bucket: str,
                         participant_id: UUID | None) -> list[dict]:
    """Consumption and feed-in per participant (all meters of the participant summed).

    shared_kwh is the participant's share of the community's shared energy, calculated
    per quarter as participant from_grid / total from_grid * shared_kwh, then summed
    per bucket (CONTEXT.md, Simultaneity). Meters without a participant are left out.
    """
    params: dict[str, Any] = {"start": start, "end": end, "width": BUCKETS[bucket],
                              "tz": config.TIMEZONE}
    where = _participant_filter("m.participant_id", participant_id, params)
    return db.all(
        "WITH quarters AS ("
        "  SELECT m.participant_id, r.ts, sum(r.to_grid_kwh) AS to_grid, "
        "         sum(r.from_grid_kwh) AS from_grid "
        "  FROM readings r JOIN meters m ON m.meter_reference = r.meter_reference "
        "  WHERE r.ts >= %(start)s AND r.ts < %(end)s AND m.participant_id IS NOT NULL"
        f"  {where} "
        "  GROUP BY m.participant_id, r.ts"
        ") "
        "SELECT q.participant_id, "
        "       time_bucket(%(width)s::interval, q.ts, %(tz)s) AS ts, "
        "       sum(q.to_grid) AS to_grid_kwh, sum(q.from_grid) AS from_grid_kwh, "
        "       round(sum(CASE WHEN c.total_from_grid_kwh > 0 "
        "             THEN q.from_grid / c.total_from_grid_kwh * c.shared_kwh END), 3) "
        "             AS shared_kwh, "
        "       count(*) AS quarter_count "
        "FROM quarters q LEFT JOIN community_simultaneity c ON c.ts = q.ts "
        "GROUP BY 1, 2 ORDER BY 1, 2",
        params,
    )


def community_simultaneity(db: Session, start: datetime, end: datetime,
                           bucket: str) -> list[dict]:
    """Simultaneity of the whole community; simultaneity = shared / feed-in per bucket."""
    return db.all(
        "SELECT time_bucket(%(width)s::interval, ts, %(tz)s) AS ts, "
        "       sum(total_to_grid_kwh) AS total_to_grid_kwh, "
        "       sum(total_from_grid_kwh) AS total_from_grid_kwh, "
        "       sum(shared_kwh) AS shared_kwh, "
        "       round(sum(shared_kwh) / NULLIF(sum(total_to_grid_kwh), 0), 4) AS simultaneity, "
        "       max(meter_count) AS meter_count, count(*) AS quarter_count "
        "FROM community_simultaneity WHERE ts >= %(start)s AND ts < %(end)s "
        "GROUP BY 1 ORDER BY 1",
        {"start": start, "end": end, "width": BUCKETS[bucket], "tz": config.TIMEZONE},
    )


def forecasts(db: Session, start: datetime, end: datetime,
              participant_id: UUID | None) -> list[dict]:
    """The most recent forecast per participant and quarter hour."""
    params: dict[str, Any] = {"start": start, "end": end}
    where = _participant_filter("participant_id", participant_id, params)
    return db.all(
        "SELECT DISTINCT ON (participant_id, ts) participant_id, ts, run_date, "
        "       to_grid_p10, to_grid_p50, to_grid_p90, "
        "       from_grid_p10, from_grid_p50, from_grid_p90, model_version "
        "FROM forecasts WHERE ts >= %(start)s AND ts < %(end)s"
        f"{where} ORDER BY participant_id, ts, run_date DESC",
        params,
    )


def energy_prices(db: Session, start: datetime, end: datetime) -> list[dict]:
    return db.all(
        "SELECT ts, price_eur_per_kwh FROM energy_prices "
        "WHERE ts >= %s AND ts < %s ORDER BY ts",
        [start, end],
    )


# ---------- Advice ----------

ADVICE_COLUMNS = (
    "id, participant_id, advice_date, rank, appliance_category::text AS appliance_category, "
    "suggested_start, suggested_end, impact::text AS impact, expected_shared_kwh, "
    "feedback::text AS feedback, measured_effect_kwh"
)


def advice(db: Session, start_date: date, end_date: date,
           participant_id: UUID | None) -> list[dict]:
    params: dict[str, Any] = {"start": start_date, "end": end_date}
    where = _participant_filter("participant_id", participant_id, params)
    return db.all(
        f"SELECT {ADVICE_COLUMNS} FROM advice "
        f"WHERE advice_date BETWEEN %(start)s AND %(end)s{where} "
        "ORDER BY advice_date, participant_id, rank",
        params,
    )


def set_advice_feedback(db: Session, advice_id: UUID, feedback: str | None) -> dict | None:
    """Only the feedback column; RLS limits a participant to their own advice."""
    return db.one(
        f"UPDATE advice SET feedback = %s WHERE id = %s RETURNING {ADVICE_COLUMNS}",
        [feedback, advice_id],
    )


# ---------- Appliances and comfort limits ----------

APPLIANCE_COLUMNS = (
    "id, participant_id, category::text AS category, power_kw, earliest_start, "
    "latest_end, min_run_minutes"
)


def appliances(db: Session, participant_id: UUID | None) -> list[dict]:
    params: dict[str, Any] = {}
    where = _participant_filter("participant_id", participant_id, params)
    return db.all(
        f"SELECT {APPLIANCE_COLUMNS} FROM participant_appliances WHERE true{where} "
        "ORDER BY participant_id, category",
        params,
    )


def create_appliance(db: Session, fields: Mapping[str, Any]) -> dict:
    return db.one(
        "INSERT INTO participant_appliances (participant_id, category, power_kw, "
        "earliest_start, latest_end, min_run_minutes) VALUES (%(participant_id)s, "
        "%(category)s, %(power_kw)s, %(earliest_start)s, %(latest_end)s, %(min_run_minutes)s) "
        f"RETURNING {APPLIANCE_COLUMNS}",
        fields,
    )


def update_appliance(db: Session, appliance_id: UUID, fields: Mapping[str, Any]) -> dict | None:
    """Only comfort limits (the database refuses other columns for web_participant)."""
    query = _update("participant_appliances", fields, "id", appliance_id, APPLIANCE_COLUMNS)
    return db.one(query, {**fields, "_key": appliance_id})


def delete_appliance(db: Session, appliance_id: UUID) -> int:
    return db.execute("DELETE FROM participant_appliances WHERE id = %s", [appliance_id])


# ---------- Imports ----------

IMPORT_COLUMNS = (
    "id, file_name, status::text AS status, period_start, period_end, row_count, "
    "new_meter_count, error_message, started_at"
)


def list_imports(db: Session, limit: int) -> list[dict]:
    return db.all(
        f"SELECT {IMPORT_COLUMNS} FROM import_log ORDER BY started_at DESC LIMIT %s", [limit]
    )


def get_import(db: Session, import_id: UUID) -> dict | None:
    return db.one(f"SELECT {IMPORT_COLUMNS} FROM import_log WHERE id = %s", [import_id])


# ---------- Settings ----------


def list_settings(db: Session) -> list[dict]:
    return db.all("SELECT key, value, updated_at FROM settings ORDER BY key")


def put_setting(db: Session, key: str, value: Any) -> dict:
    return db.one(
        "INSERT INTO settings (key, value) VALUES (%s, %s) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now() "
        "RETURNING key, value, updated_at",
        [key, Jsonb(value)],
    )
