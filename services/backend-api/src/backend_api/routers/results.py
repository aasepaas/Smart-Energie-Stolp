"""Simultaneity, forecasts, energy prices and advice."""

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime

from ..auth import allow
from ..db import get_cursor
from ..schemas import (Advice, AdviceDay, AdviceEffect, Count, EnergyPrice, Forecast,
                       SimultaneityPeriod, SimultaneityRow, batch)

router = APIRouter(tags=["results"])


# ---------- Simultaneity (Data processing service) ----------

@router.get("/simultaneity", response_model=list[SimultaneityRow],
            dependencies=[allow("processing", "training", "forecast")])
def list_simultaneity(start: AwareDatetime, end: AwareDatetime, cur=Depends(get_cursor)):
    """Simultaneity of the whole community per quarter hour in [start, end)."""
    cur.execute(
        "SELECT ts, total_to_grid_kwh, total_from_grid_kwh, shared_kwh, meter_count "
        "FROM community_simultaneity WHERE ts >= %s AND ts < %s ORDER BY ts",
        [start, end],
    )
    return cur.fetchall()


@router.put("/simultaneity", response_model=Count, dependencies=[allow("processing")])
def replace_simultaneity(body: SimultaneityPeriod, cur=Depends(get_cursor)):
    """Recalculation of a period: existing rows in [start, end) are replaced."""
    if any(not (body.start <= r.ts < body.end) for r in body.rows):
        raise HTTPException(422, "All rows must fall within [start, end)")
    cur.execute("DELETE FROM community_simultaneity WHERE ts >= %s AND ts < %s",
                [body.start, body.end])
    cur.executemany(
        "INSERT INTO community_simultaneity "
        "(ts, total_to_grid_kwh, total_from_grid_kwh, shared_kwh, meter_count) "
        "VALUES (%s, %s, %s, %s, %s)",
        [(r.ts, r.total_to_grid_kwh, r.total_from_grid_kwh, r.shared_kwh, r.meter_count)
         for r in body.rows],
    )
    return {"count": len(body.rows)}


# ---------- Forecasts (Forecast pipeline) ----------

@router.get("/forecasts", response_model=list[Forecast],
            dependencies=[allow("training", "forecast")])
def list_forecasts(start: AwareDatetime, end: AwareDatetime,
                   run_date: date | None = None, cur=Depends(get_cursor)):
    """Forecasts in [start, end), optionally only those made on a specific evening (run_date)."""
    query = "SELECT * FROM forecasts WHERE ts >= %s AND ts < %s"
    params = [start, end]
    if run_date:
        query += " AND run_date = %s"
        params.append(run_date)
    cur.execute(query + " ORDER BY participant_id, ts", params)
    return cur.fetchall()


@router.post("/forecasts", response_model=Count, status_code=201,
             dependencies=[allow("forecast")])
def add_forecasts(rows: batch(Forecast), cur=Depends(get_cursor)):
    """Adds forecasts. A forecast that already exists (same participant, quarter hour
    and evening) is skipped: the first run of an evening is kept."""
    cur.executemany(
        "INSERT INTO forecasts (participant_id, ts, run_date, to_grid_p10, to_grid_p50, "
        "to_grid_p90, from_grid_p10, from_grid_p50, from_grid_p90, model_version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        [(r.participant_id, r.ts, r.run_date, r.to_grid_p10, r.to_grid_p50, r.to_grid_p90,
          r.from_grid_p10, r.from_grid_p50, r.from_grid_p90, r.model_version) for r in rows],
    )
    return {"count": cur.rowcount}


# ---------- Energy prices (Forecast pipeline) ----------

@router.get("/energy-prices", response_model=list[EnergyPrice],
            dependencies=[allow("forecast")])
def list_prices(start: AwareDatetime, end: AwareDatetime, cur=Depends(get_cursor)):
    """Dynamic day-ahead prices per quarter hour in [start, end)."""
    cur.execute("SELECT ts, price_eur_per_kwh FROM energy_prices "
                "WHERE ts >= %s AND ts < %s ORDER BY ts", [start, end])
    return cur.fetchall()


@router.put("/energy-prices", response_model=Count, dependencies=[allow("forecast")])
def upsert_prices(rows: batch(EnergyPrice), cur=Depends(get_cursor)):
    """Stores day-ahead prices; an existing price for the same quarter hour is overwritten."""
    cur.executemany(
        "INSERT INTO energy_prices (ts, price_eur_per_kwh) VALUES (%s, %s) "
        "ON CONFLICT (ts) DO UPDATE SET price_eur_per_kwh = EXCLUDED.price_eur_per_kwh",
        [(r.ts, r.price_eur_per_kwh) for r in rows],
    )
    return {"count": len(rows)}


# ---------- Advice ----------

@router.get("/advice", response_model=list[Advice],
            dependencies=[allow("training", "forecast")])
def list_advice(start_date: date, end_date: date, cur=Depends(get_cursor)):
    """Advice in [start_date, end_date], including feedback and measured effect."""
    cur.execute(
        "SELECT * FROM advice WHERE advice_date BETWEEN %s AND %s "
        "ORDER BY advice_date, participant_id, rank",
        [start_date, end_date],
    )
    return cur.fetchall()


@router.put("/advice", response_model=Count, dependencies=[allow("forecast")])
def replace_advice(body: AdviceDay, cur=Depends(get_cursor)):
    """Stores the top 3 advice of a day (ranker).

    On a repeated evening run, existing advice is updated; feedback and measured
    effect are kept. Ranks that no longer appear in the new run are deleted per
    participant.
    """
    cur.executemany(
        "INSERT INTO advice (participant_id, advice_date, rank, appliance_category, "
        "suggested_start, suggested_end, impact, expected_shared_kwh, acceptance_probability) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (participant_id, advice_date, rank) DO UPDATE SET "
        "appliance_category = EXCLUDED.appliance_category, "
        "suggested_start = EXCLUDED.suggested_start, suggested_end = EXCLUDED.suggested_end, "
        "impact = EXCLUDED.impact, expected_shared_kwh = EXCLUDED.expected_shared_kwh, "
        "acceptance_probability = EXCLUDED.acceptance_probability",
        [(i.participant_id, body.advice_date, i.rank, i.appliance_category, i.suggested_start,
          i.suggested_end, i.impact, i.expected_shared_kwh, i.acceptance_probability)
         for i in body.items],
    )
    ranks = defaultdict(list)
    for item in body.items:
        ranks[item.participant_id].append(item.rank)
    for participant_id, kept in ranks.items():
        cur.execute(
            "DELETE FROM advice WHERE participant_id = %s AND advice_date = %s "
            "AND NOT (rank = ANY(%s))",
            [participant_id, body.advice_date, kept],
        )
    return {"count": len(body.items)}


@router.patch("/advice/effects", response_model=Count, dependencies=[allow("training")])
def record_effects(rows: batch(AdviceEffect), cur=Depends(get_cursor)):
    """Effect measurement: stores the measured effect per advice."""
    updated = 0
    for r in rows:
        cur.execute("UPDATE advice SET measured_effect_kwh = %s WHERE id = %s",
                    [r.measured_effect_kwh, r.id])
        updated += cur.rowcount
    return {"count": updated}
