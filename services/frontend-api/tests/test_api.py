"""Integration test of the Frontend API against a real database.

Requires the database with migration 0001 (schema, roles and row-level security).
The test creates its own data (two participants in June 2098) through a superuser
connection and removes it afterwards.

    SES_DB_URL=postgresql://ses:ses@db:5432/ses \
    FRONTEND_DATABASE_URL=postgresql://ses_frontend:user@db:5432/ses \
    pytest tests/test_api.py -v

The database enum user_role only knows participant and administrator so far; viewer
and superadmin are tested with tokens made directly by the authentication module.
"""

import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from frontend_api import authentication, query_builder
from frontend_api.authentication import Principal
from frontend_api.main import app
from frontend_api.query_executor import get_session

ADMIN_URL = os.environ.get(
    "SES_DB_URL", os.environ.get("DATABASE_URL", "postgresql://ses:ses@localhost:5432/ses")
)
T0 = "2098-06-01T12:00:00+00:00"
T1 = "2098-06-01T12:15:00+00:00"
START, END = "2098-06-01T00:00:00+00:00", "2098-06-02T00:00:00+00:00"
DAY = "2098-06-01"
PASSWORD = "a long test password"


def bearer(user: Principal) -> dict:
    return {"Authorization": f"Bearer {authentication.create_access_token(user)}"}


@pytest.fixture(scope="module")
def d():
    tag = uuid.uuid4().hex[:6]
    a, b = uuid.uuid4(), uuid.uuid4()
    data = {
        "tag": tag, "a": a, "b": b,
        "meter_a": f"TFA{tag}", "meter_b": f"TFB{tag}", "meter_free": f"TFU{tag}",
        "email_a": f"a-{tag}@example.org", "email_admin": f"admin-{tag}@example.org",
    }
    pw_hash = authentication.hash_password(PASSWORD)
    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute("INSERT INTO participants (id, name) VALUES (%s, %s), (%s, %s)",
                  [a, f"test-fapi-{tag}-a", b, f"test-fapi-{tag}-b"])
        c.execute("INSERT INTO meters VALUES (%s, %s), (%s, %s), (%s, NULL)",
                  [data["meter_a"], a, data["meter_b"], b, data["meter_free"]])
        # A feeds in, B consumes: shared 1.0 at T0 (all for B), 1.0 at T1 (half each)
        c.cursor().executemany("INSERT INTO readings VALUES (%s, %s, %s, %s)", [
            (data["meter_a"], T0, 2, 0), (data["meter_b"], T0, 0, 1),
            (data["meter_a"], T1, 1, 1), (data["meter_b"], T1, 0, 1),
        ])
        c.cursor().executemany("INSERT INTO community_simultaneity VALUES (%s, %s, %s, %s, 2)",
                      [(T0, 2, 1, 1), (T1, 1, 2, 1)])
        c.cursor().executemany(
            "INSERT INTO forecasts (participant_id, ts, run_date, from_grid_p50, model_version) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(a, T0, "2098-05-30", 9, "old"), (a, T0, "2098-05-31", 1, "new"),
             (b, T0, "2098-05-31", 2, "new")],
        )
        c.cursor().executemany("INSERT INTO energy_prices VALUES (%s, %s)",
                               [(T0, 0.21), (T1, -0.01)])
        for pid in (a, b):
            c.execute(
                "INSERT INTO advice (participant_id, advice_date, rank, appliance_category, "
                "suggested_start, suggested_end, impact, expected_shared_kwh) "
                "VALUES (%s, %s, 1, 'transport', %s, %s, 'high', 3.5) RETURNING id",
                [pid, DAY, T0, T1],
            )
            data[f"advice_{'a' if pid == a else 'b'}"] = c.execute(
                "SELECT id FROM advice WHERE participant_id = %s", [pid]).fetchone()[0]
            data[f"appliance_{'a' if pid == a else 'b'}"] = c.execute(
                "INSERT INTO participant_appliances (participant_id, category, power_kw, "
                "earliest_start, latest_end, min_run_minutes) "
                "VALUES (%s, 'heat_pump', 3, '22:00', '07:00', 60) RETURNING id", [pid],
            ).fetchone()[0]
        data["user_a"] = c.execute(
            "INSERT INTO users (email, password_hash, role, participant_id) "
            "VALUES (%s, %s, 'participant', %s) RETURNING id", [data["email_a"], pw_hash, a],
        ).fetchone()[0]
        data["user_admin"] = c.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (%s, %s, 'administrator') "
            "RETURNING id", [data["email_admin"], pw_hash],
        ).fetchone()[0]

    data["participant"] = Principal(data["user_a"], "participant", a)
    data["admin"] = Principal(data["user_admin"], "administrator", None)
    data["viewer"] = Principal(uuid.uuid4(), "viewer", None)
    data["superadmin"] = Principal(uuid.uuid4(), "superadmin", None)
    with TestClient(app) as client:
        data["client"] = client
        yield data

    with psycopg.connect(ADMIN_URL, autocommit=True) as c:
        c.execute("DELETE FROM users WHERE email LIKE %s", [f"%-{tag}@example.org"])
        c.execute("DELETE FROM participants WHERE name LIKE %s", [f"test-fapi-{tag}%"])
        c.execute("DELETE FROM readings WHERE meter_reference LIKE %s", [f"TF_{tag}"])
        c.execute("DELETE FROM meters WHERE meter_reference LIKE %s", [f"TF_{tag}"])
        c.execute("DELETE FROM community_simultaneity WHERE ts >= %s AND ts < %s", [START, END])
        c.execute("DELETE FROM energy_prices WHERE ts >= %s AND ts < %s", [START, END])
        c.execute("DELETE FROM settings WHERE key = %s", [f"test_{tag}"])


# ---------- Authentication ----------


def test_health(d):
    assert d["client"].get("/health").json() == {"status": "ok"}


def test_login_refresh_logout(d):
    c = d["client"]
    assert c.post("/v1/auth/login", json={"email": d["email_a"], "password": "wrong"}
                  ).status_code == 401
    assert c.post("/v1/auth/login", json={"email": "nobody@example.org", "password": PASSWORD}
                  ).status_code == 401

    r = c.post("/v1/auth/login", json={"email": d["email_a"].upper(), "password": PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == {"id": str(d["user_a"]), "role": "participant",
                            "participant_id": str(d["a"])}
    cookie = r.headers["set-cookie"]
    assert "ses_refresh=" in cookie and "HttpOnly" in cookie and "Path=/v1/auth" in cookie

    me = c.get("/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["role"] == "participant"

    r = c.post("/v1/auth/refresh")  # TestClient keeps the cookie
    assert r.status_code == 200 and r.json()["user"]["id"] == str(d["user_a"])

    assert c.post("/v1/auth/logout").status_code == 204
    assert c.post("/v1/auth/refresh").status_code == 401


def test_no_token_is_401(d):
    assert d["client"].get("/v1/simultaneity", params={"start": START, "end": END}
                           ).status_code == 401


# ---------- Permission matrix ----------


PERIOD = {"start": START, "end": END}
DAYS = {"start_date": DAY, "end_date": DAY}


@pytest.mark.parametrize("role, method, path, params, expected", [
    # everyone: prices and community simultaneity
    ("viewer", "GET", "/v1/prices", PERIOD, 200),
    ("viewer", "GET", "/v1/simultaneity", PERIOD, 200),
    # viewer: no participant data
    ("viewer", "GET", "/v1/readings", PERIOD, 403),
    ("viewer", "GET", "/v1/forecasts", PERIOD, 403),
    ("viewer", "GET", "/v1/advice", DAYS, 403),
    ("viewer", "GET", "/v1/appliances", None, 403),
    ("viewer", "GET", "/v1/participants", None, 403),
    # participant: no admin functions
    ("participant", "GET", "/v1/users", None, 403),
    ("participant", "GET", "/v1/settings", None, 403),
    ("participant", "GET", "/v1/uploads", None, 403),
    ("participant", "POST", "/v1/participants", None, 403),
    ("participant", "POST", "/v1/appliances", None, 403),
    # administrator: no feedback on someone else's advice
    ("admin", "PUT", f"/v1/advice/{uuid.uuid4()}/feedback", None, 403),
])
def test_permission_matrix(d, role, method, path, params, expected):
    r = d["client"].request(method, path, headers=bearer(d[role]), params=params,
                            json=None if method == "GET" else {})
    assert r.status_code == expected


# ---------- Energy data ----------


def test_participant_only_sees_own_readings(d):
    c, h = d["client"], bearer(d["participant"])
    rows = c.get("/v1/readings", headers=h, params={"start": START, "end": END}).json()
    assert {r["participant_id"] for r in rows} == {str(d["a"])}
    assert [r["shared_kwh"] for r in rows] == [0.0, 0.5]

    r = c.get("/v1/readings", headers=h,
              params={"start": START, "end": END, "participant_id": str(d["b"])})
    assert r.status_code == 403


def test_admin_sees_all_participants(d):
    c, h = d["client"], bearer(d["admin"])
    rows = c.get("/v1/readings", headers=h, params={"start": START, "end": END}).json()
    ours = [r for r in rows if r["participant_id"] in (str(d["a"]), str(d["b"]))]
    assert len(ours) == 4

    rows = c.get("/v1/readings", headers=h, params={
        "start": START, "end": END, "participant_id": str(d["b"]), "bucket": "hour"}).json()
    assert rows == [{"participant_id": str(d["b"]), "ts": "2098-06-01T12:00:00Z",
                     "to_grid_kwh": 0.0, "from_grid_kwh": 2.0, "shared_kwh": 1.5,
                     "quarter_count": 2}]


def test_row_level_security_is_second_check(d):
    """Even if the API forgot the participant filter, the database only returns own rows."""
    sessions = get_session(d["participant"])
    db = next(sessions)
    try:
        rows = query_builder.participant_readings(db, T0, END, "quarter", None)
        assert {r["participant_id"] for r in rows} == {d["a"]}
        assert {p["id"] for p in query_builder.list_participants(db)} == {d["a"]}
        meters = query_builder.list_meters(db, False)
        assert {m["meter_reference"] for m in meters} == {d["meter_a"]}
    finally:
        sessions.close()


def test_simultaneity_with_summary(d):
    r = d["client"].get("/v1/simultaneity", headers=bearer(d["viewer"]),
                        params={"start": START, "end": END, "bucket": "day"}).json()
    assert r["summary"] == {"total_to_grid_kwh": 3.0, "total_from_grid_kwh": 3.0,
                            "shared_kwh": 2.0, "simultaneity": 0.6667, "quarter_count": 2}
    # one Dutch day: starts at 22:00 UTC the evening before (summer time)
    assert [row["ts"] for row in r["rows"]] == ["2098-05-31T22:00:00Z"]


def test_forecasts_latest_run(d):
    rows = d["client"].get("/v1/forecasts", headers=bearer(d["participant"]),
                           params={"start": START, "end": END}).json()
    assert len(rows) == 1 and rows[0]["model_version"] == "new"
    assert rows[0]["from_grid_p50"] == 1.0


def test_prices(d):
    rows = d["client"].get("/v1/prices", headers=bearer(d["participant"]),
                           params={"start": START, "end": END}).json()
    assert [r["price_eur_per_kwh"] for r in rows] == [0.21, -0.01]


@pytest.mark.parametrize("params", [
    {"start": END, "end": START},
    {"start": START, "end": "2100-01-01T00:00:00+00:00"},
    {"start": "2098-06-01T00:00:00", "end": END},  # no time zone
])
def test_invalid_period_is_422(d, params):
    r = d["client"].get("/v1/prices", headers=bearer(d["admin"]), params=params)
    assert r.status_code == 422


# ---------- Advice ----------


def test_advice_and_feedback(d):
    c, h = d["client"], bearer(d["participant"])
    rows = c.get("/v1/advice", headers=h, params={"start_date": DAY, "end_date": DAY}).json()
    assert [r["id"] for r in rows] == [str(d["advice_a"])]

    r = c.put(f"/v1/advice/{d['advice_a']}/feedback", headers=h, json={"feedback": "accepted"})
    assert r.status_code == 200 and r.json()["feedback"] == "accepted"

    # someone else's advice does not exist for this participant
    r = c.put(f"/v1/advice/{d['advice_b']}/feedback", headers=h, json={"feedback": "rejected"})
    assert r.status_code == 404


# ---------- Appliances ----------


def test_participant_changes_own_comfort_limits(d):
    c, h = d["client"], bearer(d["participant"])
    r = c.patch(f"/v1/appliances/{d['appliance_a']}", headers=h,
                json={"earliest_start": "23:00:00", "min_run_minutes": 90})
    assert r.status_code == 200
    assert r.json()["earliest_start"] == "23:00:00" and r.json()["min_run_minutes"] == 90

    assert c.patch(f"/v1/appliances/{d['appliance_b']}", headers=h,
                   json={"min_run_minutes": 30}).status_code == 404
    assert c.patch(f"/v1/appliances/{d['appliance_a']}", headers=h,
                   json={"participant_id": str(d["b"])}).status_code == 422  # no such field
    assert c.patch(f"/v1/appliances/{d['appliance_a']}", headers=h,
                   json={"min_run_minutes": None}).status_code == 422


def test_admin_manages_appliances(d):
    c, h = d["client"], bearer(d["admin"])
    body = {"participant_id": str(d["b"]), "category": "transport", "power_kw": "11",
            "earliest_start": "18:00", "latest_end": "07:00", "min_run_minutes": 120}
    r = c.post("/v1/appliances", headers=h, json=body)
    assert r.status_code == 201
    assert c.post("/v1/appliances", headers=h, json=body).status_code == 409
    assert c.delete(f"/v1/appliances/{r.json()['id']}", headers=h).status_code == 204


# ---------- Participants and meters ----------


def test_admin_links_meter(d):
    c, h = d["client"], bearer(d["admin"])
    unlinked = c.get("/v1/meters", headers=h, params={"unlinked": "true"}).json()
    assert d["meter_free"] in {m["meter_reference"] for m in unlinked}

    path = f"/v1/meters/{d['meter_free']}/participant"
    assert c.put(path, headers=bearer(d["participant"]),
                 json={"participant_id": str(d["a"])}).status_code == 403
    r = c.put(path, headers=h, json={"participant_id": str(d["b"])})
    assert r.status_code == 200 and r.json()["participant_id"] == str(d["b"])
    assert c.put(path, headers=h, json={"participant_id": str(uuid.uuid4())}).status_code == 422
    assert c.put("/v1/meters/NOPE/participant", headers=h,
                 json={"participant_id": None}).status_code == 404


def test_admin_manages_participants(d):
    c, h = d["client"], bearer(d["admin"])
    name = f"test-fapi-{d['tag']}-c"
    r = c.post("/v1/participants", headers=h, json={"name": name})
    assert r.status_code == 201 and r.json()["meter_references"] == []
    assert c.post("/v1/participants", headers=h, json={"name": name}).status_code == 409
    pid = r.json()["id"]
    r = c.patch(f"/v1/participants/{pid}", headers=h, json={"name": name + "x"})
    assert r.json()["name"] == name + "x"
    assert c.delete(f"/v1/participants/{pid}", headers=h).status_code == 204
    assert c.delete(f"/v1/participants/{pid}", headers=h).status_code == 404


# ---------- Settings and uploads ----------


def test_settings(d):
    c, h, key = d["client"], bearer(d["admin"]), f"test_{d['tag']}"
    r = c.put(f"/v1/settings/{key}", headers=h, json={"value": {"KV": 13.8}})
    assert r.status_code == 200 and r.json()["value"] == {"KV": 13.8}
    c.put(f"/v1/settings/{key}", headers=h, json={"value": [1, 2]})
    assert {"key": key, "value": [1, 2]}.items() <= next(
        s for s in c.get("/v1/settings", headers=h).json() if s["key"] == key).items()
    assert c.put("/v1/settings/Bad-Key", headers=h, json={"value": 1}).status_code == 422


def test_upload_list(d):
    r = d["client"].get("/v1/uploads", headers=bearer(d["admin"]))
    assert r.status_code == 200
    assert d["client"].get(f"/v1/uploads/{uuid.uuid4()}",
                           headers=bearer(d["admin"])).status_code == 404


# ---------- Accounts ----------


def test_admin_manages_participant_accounts(d):
    c, h = d["client"], bearer(d["admin"])
    email = f"b-{d['tag']}@example.org"
    body = {"email": email, "password": PASSWORD, "role": "participant",
            "participant_id": str(d["b"])}
    r = c.post("/v1/users", headers=h, json=body)
    assert r.status_code == 201
    user_id = r.json()["id"]
    assert c.post("/v1/users", headers=h, json=body).status_code == 409
    assert "password_hash" not in r.json()

    login = c.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login.json()["user"]["participant_id"] == str(d["b"])

    r = c.patch(f"/v1/users/{user_id}", headers=h, json={"password": "another long password"})
    assert r.status_code == 200
    assert c.post("/v1/auth/login", json={"email": email, "password": PASSWORD}).status_code == 401

    # a participant account needs a participant
    assert c.patch(f"/v1/users/{user_id}", headers=h,
                   json={"participant_id": None}).status_code == 422
    assert c.post("/v1/users", headers=h, json={**body, "password": "short"}).status_code == 422
    assert c.delete(f"/v1/users/{user_id}", headers=h).status_code == 204


def test_only_superadmin_manages_admin_accounts(d):
    c = d["client"]
    body = {"email": f"admin2-{d['tag']}@example.org", "password": PASSWORD,
            "role": "administrator"}
    assert c.post("/v1/users", headers=bearer(d["admin"]), json=body).status_code == 403
    # administrator may not promote a participant account either
    assert c.patch(f"/v1/users/{d['user_a']}", headers=bearer(d["admin"]),
                   json={"role": "administrator", "participant_id": None}).status_code == 403

    r = c.post("/v1/users", headers=bearer(d["superadmin"]), json=body)
    assert r.status_code == 201
    assert c.delete(f"/v1/users/{r.json()['id']}", headers=bearer(d["admin"])).status_code == 403
    assert c.delete(f"/v1/users/{r.json()['id']}",
                    headers=bearer(d["superadmin"])).status_code == 204


def test_cannot_delete_yourself(d):
    c, h = d["client"], bearer(d["admin"])
    assert c.delete(f"/v1/users/{d['user_admin']}", headers=h).status_code == 409
