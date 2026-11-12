"""Electricity meters, readings and import log. Mainly used by the Data processing service."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg import sql
from pydantic import AwareDatetime

from ..auth import allow
from ..db import get_cursor
from ..schemas import Count, ImportRecord, ImportStart, ImportUpdate, Meter, NewMeters, Reading, batch

router = APIRouter(tags=["meterdata"])


@router.get("/meters", response_model=list[Meter],
            dependencies=[allow("processing", "training", "forecast")])
def list_meters(cur=Depends(get_cursor, scope="function")):
    """All meters with the participant they are linked to (meter linker)."""
    cur.execute("SELECT meter_reference, participant_id FROM meters ORDER BY meter_reference")
    return cur.fetchall()


@router.post("/meters", response_model=Count, dependencies=[allow("processing")])
def add_meters(body: NewMeters, cur=Depends(get_cursor, scope="function")):
    """Adds new meters; meters that already exist are skipped."""
    cur.executemany(
        "INSERT INTO meters (meter_reference) VALUES (%s) ON CONFLICT DO NOTHING",
        [(m,) for m in body.meter_references],
    )
    return {"count": cur.rowcount}


@router.get("/readings", response_model=list[Reading],
            dependencies=[allow("processing", "training", "forecast")])
def list_readings(
    start: AwareDatetime,
    end: AwareDatetime,
    meter_reference: list[str] | None = Query(None),
    cur=Depends(get_cursor, scope="function"),
):
    """Readings in [start, end), optionally for specific meters only."""
    query = ("SELECT meter_reference, ts, to_grid_kwh, from_grid_kwh FROM readings "
             "WHERE ts >= %s AND ts < %s")
    params = [start, end]
    if meter_reference:
        query += " AND meter_reference = ANY(%s)"
        params.append(meter_reference)
    cur.execute(query + " ORDER BY ts, meter_reference", params)
    return cur.fetchall()


@router.put("/readings", response_model=Count, dependencies=[allow("processing")])
def upsert_readings(rows: batch(Reading), cur=Depends(get_cursor, scope="function")):
    """Stores readings. Importing again overwrites existing values and creates no duplicates."""
    cur.executemany(
        "INSERT INTO readings (meter_reference, ts, to_grid_kwh, from_grid_kwh) "
        "VALUES (%s, %s, %s, %s) "
        "ON CONFLICT (meter_reference, ts) DO UPDATE SET "
        "to_grid_kwh = EXCLUDED.to_grid_kwh, from_grid_kwh = EXCLUDED.from_grid_kwh",
        [(r.meter_reference, r.ts, r.to_grid_kwh, r.from_grid_kwh) for r in rows],
    )
    return {"count": len(rows)}


@router.post("/imports", response_model=ImportRecord, status_code=201,
             dependencies=[allow("processing")])
def start_import(body: ImportStart, cur=Depends(get_cursor, scope="function")):
    """Registers a new import. The same CSV file (same hash) returns 409."""
    cur.execute(
        "INSERT INTO import_log (file_name, file_hash, period_start, period_end) "
        "VALUES (%s, %s, %s, %s) "
        "RETURNING id, file_name, status, row_count, new_meter_count, error_message, started_at",
        [body.file_name, body.file_hash, body.period_start, body.period_end],
    )
    return cur.fetchone()


@router.patch("/imports/{import_id}", response_model=ImportRecord,
              dependencies=[allow("processing")])
def update_import(import_id: UUID, body: ImportUpdate, cur=Depends(get_cursor, scope="function")):
    """Updates the status and result of an import."""
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(422, "No fields to update")
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(k), sql.Placeholder(k)) for k in fields
    )
    cur.execute(
        sql.SQL("UPDATE import_log SET {} WHERE id = {} "
                "RETURNING id, file_name, status, row_count, new_meter_count, "
                "error_message, started_at").format(assignments, sql.Placeholder("id")),
        {**fields, "id": import_id},
    )
    row = cur.fetchone()
    if row is None:
        raise HTTPException(404, "Import not found")
    return row
