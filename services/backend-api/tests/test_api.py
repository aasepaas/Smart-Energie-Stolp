"""Integratietest van de Backend API tegen een echte database.

Vereist: de database met het schema en rollen_en_rechten.sql uitgevoerd.
De test maakt eigen testdata aan (meters TEST..., datum 2099) en ruimt die
daarna op via een superuser-verbinding.

    SES_DB_URL=postgresql://ses:ses@db:5432/ses \
    BACKEND_DATABASE_URL=postgresql://ses_backend:user@db:5432/ses \
    pytest tests/test_api.py -v
"""

import os
import uuid

import psycopg
import pytest

TOKENS = {
    "processing": "test-processing",
    "training": "test-training",
    "forecast": "test-forecast",
}
os.environ.setdefault("SES_TOKEN_PROCESSING", TOKENS["processing"])
os.environ.setdefault("SES_TOKEN_TRAINING", TOKENS["training"])
os.environ.setdefault("SES_TOKEN_FORECAST", TOKENS["forecast"])

from fastapi.testclient import TestClient  # noqa: E402

from backend_api.main import app  # noqa: E402

ADMIN_URL = os.environ.get(
    "SES_DB_URL",
    os.environ.get("DATABASE_URL", "postgresql://ses:ses@localhost:5432/ses"),
)
TS = "2099-01-01T12:00:00+00:00"
TS_END = "2099-01-01T13:00:00+00:00"
DAY = "2099-01-01"


def h(service):
    return {"Authorization": f"Bearer {os.environ[f'SES_TOKEN_{service.upper()}']}"}


@pytest.fixture(scope="module")
def setup():
    tag = uuid.uuid4().hex[:6]
    pid = uuid.uuid4()
    d = {"pid": pid, "meter": f"TEST{tag}", "hash": uuid.uuid4().hex * 2}
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute(
            "INSERT INTO participants (id, name) VALUES (%s, %s)",
            [pid, f"test-api-{tag}"],
        )
        c.execute(
            "INSERT INTO participant_appliances (participant_id, category, power_kw, "
            "earliest_start, latest_end, min_run_minutes) VALUES (%s, 'transport', 11, '08:00', '18:00', 60)",
            [pid],
        )
    with TestClient(app) as client:
        d["client"] = client
        yield d
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute("DELETE FROM readings WHERE meter_reference = %s", [d["meter"]])
        c.execute("DELETE FROM meters WHERE meter_reference = %s", [d["meter"]])
        c.execute("DELETE FROM import_log WHERE file_hash = %s", [d["hash"]])
        c.execute("DELETE FROM community_simultaneity WHERE ts >= '2099-01-01'")
        c.execute("DELETE FROM energy_prices WHERE ts >= '2099-01-01'")
        c.execute(
            "DELETE FROM participants WHERE id = %s", [pid]
        )  # cascade: advice, forecasts, apparaten


def test_health(setup):
    assert setup["client"].get("/health").json() == {"status": "ok"}


def test_zonder_of_met_fout_token_401(setup):
    c = setup["client"]
    assert c.get("/v1/meters").status_code == 401
    assert (
        c.get("/v1/meters", headers={"Authorization": "Bearer fout"}).status_code == 401
    )


@pytest.mark.parametrize(
    "service, method, path",
    [
        ("training", "put", "/v1/readings"),
        ("forecast", "post", "/v1/meters"),
        ("processing", "get", "/v1/appliances"),
        ("processing", "put", "/v1/advice"),
        ("training", "put", "/v1/energy-prices"),
        ("forecast", "patch", "/v1/advice/effects"),
    ],
)
def test_service_buiten_eigen_endpoints_403(setup, service, method, path):
    r = setup["client"].request(
        method.upper(), path, headers=h(service), json=None if method == "get" else []
    )
    assert r.status_code == 403


def test_import_flow(setup):
    c, meter = setup["client"], setup["meter"]
    r = c.post(
        "/v1/imports",
        headers=h("processing"),
        json={"file_name": "test.csv", "file_hash": setup["hash"]},
    )
    assert r.status_code == 201 and r.json()["status"] == "running"
    import_id = r.json()["id"]

    assert (
        c.post(
            "/v1/imports",
            headers=h("processing"),
            json={"file_name": "test.csv", "file_hash": setup["hash"]},
        ).status_code
        == 409
    )

    assert c.post(
        "/v1/meters", headers=h("processing"), json={"meter_references": [meter]}
    ).json() == {"count": 1}
    assert c.post(
        "/v1/meters", headers=h("processing"), json={"meter_references": [meter]}
    ).json() == {"count": 0}

    row = {
        "meter_reference": meter,
        "ts": TS,
        "to_grid_kwh": "1.250",
        "from_grid_kwh": "0",
    }
    assert c.put("/v1/readings", headers=h("processing"), json=[row]).status_code == 200
    row["to_grid_kwh"] = "2.500"
    c.put(
        "/v1/readings", headers=h("processing"), json=[row]
    )  # upsert, geen dubbele rij
    got = c.get(
        "/v1/readings",
        headers=h("training"),
        params={
            "start": TS,
            "end": "2099-01-02T00:00:00+00:00",
            "meter_reference": meter,
        },
    ).json()
    assert len(got) == 1 and got[0]["to_grid_kwh"] == "2.500"

    r = c.patch(
        f"/v1/imports/{import_id}",
        headers=h("processing"),
        json={"status": "succeeded", "row_count": 1, "new_meter_count": 1},
    )
    assert r.json()["status"] == "succeeded"


def test_gelijktijdigheid_vervangen(setup):
    c = setup["client"]
    body = {
        "start": TS,
        "end": "2099-01-01T13:00:00+00:00",
        "rows": [
            {
                "ts": TS,
                "total_to_grid_kwh": 3,
                "total_from_grid_kwh": 2,
                "shared_kwh": 2,
                "meter_count": 2,
            }
        ],
    }
    assert c.put("/v1/simultaneity", headers=h("processing"), json=body).json() == {
        "count": 1
    }
    assert c.put("/v1/simultaneity", headers=h("processing"), json=body).json() == {
        "count": 1
    }
    got = c.get(
        "/v1/simultaneity",
        headers=h("forecast"),
        params={"start": TS, "end": "2099-01-01T13:00:00+00:00"},
    ).json()
    assert len(got) == 1


def test_avondrun(setup):
    c, pid = setup["client"], str(setup["pid"])
    assert any(
        a["participant_id"] == pid
        for a in c.get("/v1/appliances", headers=h("forecast")).json()
    )

    assert (
        c.put(
            "/v1/energy-prices",
            headers=h("forecast"),
            json=[{"ts": TS, "price_eur_per_kwh": "0.25"}],
        ).status_code
        == 200
    )

    fc = {
        "participant_id": pid,
        "ts": TS,
        "run_date": "2098-12-31",
        "to_grid_p50": "1.0",
        "model_version": "test",
    }
    assert c.post("/v1/forecasts", headers=h("forecast"), json=[fc]).json() == {
        "count": 1
    }
    assert c.post("/v1/forecasts", headers=h("forecast"), json=[fc]).json() == {
        "count": 0
    }

    def item(rank, cat):
        return {
            "participant_id": pid,
            "rank": rank,
            "appliance_category": cat,
            "suggested_start": TS,
            "suggested_end": TS_END,
            "impact": "high",
            "expected_shared_kwh": "6",
            "acceptance_probability": "0.3",
        }

    c.put(
        "/v1/advice",
        headers=h("forecast"),
        json={
            "advice_date": DAY,
            "items": [item(1, "transport"), item(2, "heat_pump")],
        },
    )

    # De deelnemer geeft feedback (via de Frontend API; hier rechtstreeks als superuser)
    with psycopg.connect(ADMIN_URL, autocommit=True) as conn:
        conn.execute(
            "UPDATE advice SET feedback = 'accepted' WHERE participant_id = %s AND rank = 1",
            [pid],
        )

    # Tweede run: rank 1 verandert, rank 2 vervalt; de feedback op rank 1 blijft
    c.put(
        "/v1/advice",
        headers=h("forecast"),
        json={"advice_date": DAY, "items": [item(1, "air_conditioning")]},
    )
    advice = [
        a
        for a in c.get(
            "/v1/advice",
            headers=h("training"),
            params={"start_date": DAY, "end_date": DAY},
        ).json()
        if a["participant_id"] == pid
    ]
    assert [(a["rank"], a["appliance_category"], a["feedback"]) for a in advice] == [
        (1, "air_conditioning", "accepted")
    ]

    r = c.patch(
        "/v1/advice/effects",
        headers=h("training"),
        json=[{"id": advice[0]["id"], "measured_effect_kwh": "1.5"}],
    )
    assert r.json() == {"count": 1}


def test_validatie_422(setup):
    c = setup["client"]
    bad = {
        "meter_reference": "X",
        "ts": "2099-01-01T12:00:00",
        "to_grid_kwh": 1,
        "from_grid_kwh": 0,
    }  # zonder tijdzone
    assert c.put("/v1/readings", headers=h("processing"), json=[bad]).status_code == 422
    assert (
        c.put(
            "/v1/advice",
            headers=h("forecast"),
            json={"advice_date": DAY, "items": [{"rank": 4}]},
        ).status_code
        == 422
    )
    eind_voor_begin = {
        "participant_id": str(setup["pid"]),
        "rank": 1,
        "appliance_category": "transport",
        "suggested_start": TS_END,
        "suggested_end": TS,
        "impact": "high",
        "expected_shared_kwh": "6",
    }
    assert (
        c.put(
            "/v1/advice",
            headers=h("forecast"),
            json={"advice_date": DAY, "items": [eind_voor_begin]},
        ).status_code
        == 422
    )
