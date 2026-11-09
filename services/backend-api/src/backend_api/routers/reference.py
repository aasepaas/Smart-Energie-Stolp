"""Deelnemers, apparaten en instellingen (alleen lezen)."""

from fastapi import APIRouter, Depends

from ..auth import allow
from ..db import get_cursor
from ..schemas import Appliance, Participant, Setting

router = APIRouter(tags=["referentiedata"])


@router.get("/participants", response_model=list[Participant],
            dependencies=[allow("training", "forecast")])
def list_participants(cur=Depends(get_cursor)):
    cur.execute("SELECT id, name FROM participants ORDER BY name")
    return cur.fetchall()


@router.get("/appliances", response_model=list[Appliance], dependencies=[allow("forecast")])
def list_appliances(cur=Depends(get_cursor)):
    """Flexibele apparaten en comfortgrenzen per deelnemer (invoer voor de optimizer)."""
    cur.execute("SELECT id, participant_id, category, power_kw, earliest_start, latest_end, "
                "min_run_minutes FROM participant_appliances ORDER BY participant_id, category")
    return cur.fetchall()


@router.get("/settings", response_model=list[Setting],
            dependencies=[allow("processing", "training", "forecast")])
def list_settings(cur=Depends(get_cursor)):
    cur.execute("SELECT key, value FROM settings ORDER BY key")
    return cur.fetchall()
