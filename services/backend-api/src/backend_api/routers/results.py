"""Gelijktijdigheid, voorspellingen, prijzen en advies."""

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime

from ..auth import allow
from ..db import get_cursor
from ..schemas import (Advice, AdviceDay, AdviceEffect, Count, EnergyPrice, Forecast,
                       SimultaneityPeriod, SimultaneityRow, batch)

router = APIRouter(tags=["resultaten"])


# ---------- Gelijktijdigheid (Data processing service) ----------

@router.get("/simultaneity", response_model=list[SimultaneityRow],
            dependencies=[allow("processing", "training", "forecast")])
def list_simultaneity(start: AwareDatetime, end: AwareDatetime, cur=Depends(get_cursor)):
    cur.execute(
        "SELECT ts, total_to_grid_kwh, total_from_grid_kwh, shared_kwh, meter_count "
        "FROM community_simultaneity WHERE ts >= %s AND ts < %s ORDER BY ts",
        [start, end],
    )
    return cur.fetchall()


@router.put("/simultaneity", response_model=Count, dependencies=[allow("processing")])
def replace_simultaneity(body: SimultaneityPeriod, cur=Depends(get_cursor)):
    """Herberekening van een periode: oude rijen in [start, end) worden vervangen."""
    if any(not (body.start <= r.ts < body.end) for r in body.rows):
        raise HTTPException(422, "Alle rijen moeten binnen [start, end) vallen")
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


# ---------- Voorspellingen (Forecast pipeline) ----------

@router.get("/forecasts", response_model=list[Forecast],
            dependencies=[allow("training", "forecast")])
def list_forecasts(start: AwareDatetime, end: AwareDatetime,
                   run_date: date | None = None, cur=Depends(get_cursor)):
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
    """Voegt voorspellingen toe. Een voorspelling die er al is (zelfde deelnemer,
    kwartier en avond) wordt overgeslagen: de eerste run van een avond blijft staan."""
    cur.executemany(
        "INSERT INTO forecasts (participant_id, ts, run_date, to_grid_p10, to_grid_p50, "
        "to_grid_p90, from_grid_p10, from_grid_p50, from_grid_p90, model_version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        [(r.participant_id, r.ts, r.run_date, r.to_grid_p10, r.to_grid_p50, r.to_grid_p90,
          r.from_grid_p10, r.from_grid_p50, r.from_grid_p90, r.model_version) for r in rows],
    )
    return {"count": cur.rowcount}


# ---------- Prijzen (Forecast pipeline) ----------

@router.get("/energy-prices", response_model=list[EnergyPrice],
            dependencies=[allow("forecast")])
def list_prices(start: AwareDatetime, end: AwareDatetime, cur=Depends(get_cursor)):
    cur.execute("SELECT ts, price_eur_per_kwh FROM energy_prices "
                "WHERE ts >= %s AND ts < %s ORDER BY ts", [start, end])
    return cur.fetchall()


@router.put("/energy-prices", response_model=Count, dependencies=[allow("forecast")])
def upsert_prices(rows: batch(EnergyPrice), cur=Depends(get_cursor)):
    cur.executemany(
        "INSERT INTO energy_prices (ts, price_eur_per_kwh) VALUES (%s, %s) "
        "ON CONFLICT (ts) DO UPDATE SET price_eur_per_kwh = EXCLUDED.price_eur_per_kwh",
        [(r.ts, r.price_eur_per_kwh) for r in rows],
    )
    return {"count": len(rows)}


# ---------- Advies ----------

@router.get("/advice", response_model=list[Advice],
            dependencies=[allow("training", "forecast")])
def list_advice(start_date: date, end_date: date, cur=Depends(get_cursor)):
    """Advies in [start_date, end_date], inclusief feedback en gemeten effect."""
    cur.execute(
        "SELECT * FROM advice WHERE advice_date BETWEEN %s AND %s "
        "ORDER BY advice_date, participant_id, rank",
        [start_date, end_date],
    )
    return cur.fetchall()


@router.put("/advice", response_model=Count, dependencies=[allow("forecast")])
def replace_advice(body: AdviceDay, cur=Depends(get_cursor)):
    """Schrijft het top-3-advies van een dag (ranker).

    Bij een herhaalde avondrun wordt bestaand advies bijgewerkt; feedback en
    gemeten effect blijven staan. Ranks die in de nieuwe run niet meer voorkomen,
    worden per deelnemer verwijderd.
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
    """Effectmeting: legt per advies het gemeten effect vast."""
    updated = 0
    for r in rows:
        cur.execute("UPDATE advice SET measured_effect_kwh = %s WHERE id = %s",
                    [r.measured_effect_kwh, r.id])
        updated += cur.rowcount
    return {"count": updated}
