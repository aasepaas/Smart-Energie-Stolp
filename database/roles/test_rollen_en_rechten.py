"""
Geautomatiseerde test van de rollen en rechten van Smart Energie Stolp.

Controleert of de rollen en rechten uit migratie 0001 kloppen met het
ontwerp in README.md:

  1. Rollen: bestaan ze, met de juiste eigenschappen en lidmaatschappen?
  2. Rechtenmatrix: heeft elke groepsrol precies de rechten uit de README,
     per tabel, per kolom en per actie (R, I, W, D)?
  3. Row-level security: ziet een deelnemer echt alleen zijn eigen rijen?
  4. Gedrag: kloppen de bijzondere regels, zoals alleen feedback wijzigen?
  5. Inloggen: kunnen de vier inlogrollen inloggen en van rol wisselen?

De tests 1 tot en met 4 draaien in één transactie die aan het eind wordt
teruggedraaid. Er blijft dus geen testdata achter in de database.

Uitvoeren (in de dev-container staan de variabelen al goed):

    pip install pytest "psycopg[binary]"
    pytest test_rollen_en_rechten.py -v

Instellingen via omgevingsvariabelen:

    SES_DB_URL             verbinding als superuser (standaard: DATABASE_URL,
                           anders postgresql://ses:ses@localhost:5432/ses)
    SES_PASSWORD_FRONTEND  wachtwoord ses_frontend  (standaard: user)
    SES_PASSWORD_BACKEND   wachtwoord ses_backend   (standaard: user)
    SES_PASSWORD_DBA       wachtwoord ses_dba       (standaard: user)
    SES_PASSWORD_BACKUP    wachtwoord ses_backup    (standaard: user)
"""

import os
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

# ---------------------------------------------------------------------------
# Verbinding
# ---------------------------------------------------------------------------

ADMIN_URL = os.environ.get(
    "SES_DB_URL",
    os.environ.get("DATABASE_URL", "postgresql://ses:ses@localhost:5432/ses"),
)

LOGIN_PASSWORDS = {
    "ses_frontend": os.environ.get("SES_PASSWORD_FRONTEND", "user"),
    "ses_backend": os.environ.get("SES_PASSWORD_BACKEND", "user"),
    "ses_dba": os.environ.get("SES_PASSWORD_DBA", "user"),
    "ses_backup": os.environ.get("SES_PASSWORD_BACKUP", "user"),
}

# ---------------------------------------------------------------------------
# Ontwerp (README.md)
# ---------------------------------------------------------------------------

TABLES = [
    "participants", "users", "participant_appliances", "settings",
    "import_log", "meters", "readings", "community_simultaneity",
    "forecasts", "energy_prices", "advice",
]

GROUP_ROLES = ["web_participant", "web_admin", "svc_processing", "svc_training", "svc_forecast"]
LOGIN_ROLES = ["ses_dba", "ses_frontend", "ses_backend", "ses_backup"]

RLS_TABLES = ["participants", "users", "participant_appliances", "meters", "readings", "forecasts", "advice"]

ALL = "*"  # recht op alle kolommen

# Afkortingen voor de matrix
R = {"SELECT": ALL}
RI = {"SELECT": ALL, "INSERT": ALL}
RIW = {"SELECT": ALL, "INSERT": ALL, "UPDATE": ALL}
RIWD = {"SELECT": ALL, "INSERT": ALL, "UPDATE": ALL, "DELETE": True}

USERS_READABLE = {"id", "email", "role", "participant_id"}  # nooit password_hash

# Per tabel en rol: welke actie op welke kolommen. Wat hier niet staat, is verboden.
EXPECTED = {
    "participants": {
        "web_participant": R, "web_admin": RIWD,
        "svc_training": R, "svc_forecast": R,
    },
    "users": {
        "web_participant": {"SELECT": USERS_READABLE},
        "web_admin": {
            "SELECT": USERS_READABLE,
            "INSERT": ALL,
            "UPDATE": {"email", "password_hash", "role", "participant_id"},
            "DELETE": True,
        },
    },
    "participant_appliances": {
        "web_participant": {
            "SELECT": ALL,
            "UPDATE": {"power_kw", "earliest_start", "latest_end", "min_run_minutes"},
        },
        "web_admin": RIWD,
        "svc_forecast": R,
    },
    "settings": {
        "web_admin": RIW,
        "svc_processing": R, "svc_training": R, "svc_forecast": R,
    },
    "import_log": {"web_admin": RIW, "svc_processing": RIW},
    "meters": {
        "web_participant": R,
        "web_admin": {"SELECT": ALL, "UPDATE": {"participant_id"}},
        "svc_processing": RI, "svc_training": R, "svc_forecast": R,
    },
    "readings": {
        "web_participant": R, "web_admin": R,
        "svc_processing": RIW, "svc_training": R, "svc_forecast": R,
    },
    "community_simultaneity": {
        "web_participant": R, "web_admin": R,
        "svc_processing": RIWD, "svc_training": R, "svc_forecast": R,
    },
    "forecasts": {
        "web_participant": R, "web_admin": R,
        "svc_training": R, "svc_forecast": RI,
    },
    "energy_prices": {"web_participant": R, "web_admin": R, "svc_forecast": RIW},
    "advice": {
        "web_participant": {"SELECT": ALL, "UPDATE": {"feedback"}},
        "web_admin": R,
        "svc_training": {"SELECT": ALL, "UPDATE": {"measured_effect_kwh"}},
        "svc_forecast": {
            "SELECT": ALL, "INSERT": ALL, "DELETE": True,
            "UPDATE": {"appliance_category", "suggested_start", "suggested_end",
                       "impact", "expected_shared_kwh", "acceptance_probability"},
        },
    },
}

# rolnaam: (kan inloggen, erft rechten, omzeilt RLS, mag rollen aanmaken)
EXPECTED_ATTRIBUTES = {
    "ses_owner":       (False, True,  False, False),
    "ses_dba":         (True,  True,  False, True),
    "ses_frontend":    (True,  False, False, False),
    "ses_backend":     (True,  False, False, False),
    "ses_backup":      (True,  True,  True,  False),
    "web_participant": (False, True,  False, False),
    "web_admin":       (False, True,  False, False),
    "svc_processing":  (False, True,  False, False),
    "svc_training":    (False, True,  False, False),
    "svc_forecast":    (False, True,  False, False),
}

# Mag de inlogrol (links) wisselen naar de groepsrol (boven)?
EXPECTED_SET_ROLE = {
    "ses_frontend": {"web_participant": True, "web_admin": True,
                     "svc_processing": False, "svc_training": False, "svc_forecast": False},
    "ses_backend":  {"web_participant": False, "web_admin": False,
                     "svc_processing": True, "svc_training": True, "svc_forecast": True},
    "ses_dba":      {g: False for g in GROUP_ROLES},
    "ses_backup":   {g: False for g in GROUP_ROLES},
}

# ---------------------------------------------------------------------------
# Hulpmiddelen
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def conn():
    """Eén verbinding als superuser, in een transactie die nooit wordt vastgelegd."""
    try:
        c = psycopg.connect(ADMIN_URL, autocommit=False)
    except psycopg.OperationalError as e:
        pytest.exit(f"Geen verbinding met de database via {ADMIN_URL!r}: {e}", returncode=2)
    with c.cursor() as cur:
        cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
        if not cur.fetchone()[0]:
            pytest.exit("SES_DB_URL moet inloggen als superuser (bijvoorbeeld ses).", returncode=2)
    yield c
    c.rollback()
    c.close()


class als:
    """Voert een blok uit als een groepsrol, en draait daarna alles terug.

    Gebruikt een savepoint, zodat een verwachte fout (zoals permission denied)
    de rest van de tests niet verstoort.
    """

    def __init__(self, conn, role, participant_id=None):
        self.conn, self.role, self.pid = conn, role, participant_id

    def __enter__(self):
        self.cur = self.conn.cursor()
        self.cur.execute("SAVEPOINT als_rol")
        self.cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(self.role)))
        self.cur.execute("SELECT set_config('app.participant_id', %s, true)",
                         [str(self.pid) if self.pid else ""])
        return self.cur

    def __exit__(self, *exc):
        self.cur.execute("ROLLBACK TO SAVEPOINT als_rol")
        self.cur.close()
        return False


def query(conn, statement, params=None):
    with conn.cursor() as cur:
        cur.execute(statement, params)
        return cur.fetchall()


@pytest.fixture(scope="module")
def data(conn):
    """Testdata: deelnemer A en B, elk met een account, meter, meting, apparaat,
    voorspelling en advies. Alles wordt aan het eind teruggedraaid."""
    a, b = uuid.uuid4(), uuid.uuid4()
    tag = uuid.uuid4().hex[:6]
    d = {
        "a": a, "b": b,
        "meter_a": f"TA{tag}", "meter_b": f"TB{tag}",
        "email_a": f"test-a-{tag}@ses.test",
        "ts": "2099-01-01 12:00+00",
        "ts_end": "2099-01-01 13:00+00",  # suggested_end must be after suggested_start
    }
    with conn.cursor() as cur:
        cur.execute("INSERT INTO participants (id, name) VALUES (%s, %s), (%s, %s)",
                    [a, f"test-a-{tag}", b, f"test-b-{tag}"])
        cur.execute("INSERT INTO users (email, password_hash, role, participant_id) VALUES "
                    "(%s, 'HASH', 'participant', %s), (%s, 'HASH', 'participant', %s)",
                    [d["email_a"], a, f"test-b-{tag}@ses.test", b])
        cur.execute("INSERT INTO meters VALUES (%s, %s), (%s, %s)",
                    [d["meter_a"], a, d["meter_b"], b])
        cur.execute("INSERT INTO readings VALUES (%s, %s, 1, 0), (%s, %s, 0, 2)",
                    [d["meter_a"], d["ts"], d["meter_b"], d["ts"]])
        cur.execute("INSERT INTO participant_appliances (participant_id, category, power_kw, "
                    "earliest_start, latest_end, min_run_minutes) VALUES "
                    "(%s, 'transport', 11, '08:00', '18:00', 60), "
                    "(%s, 'transport', 11, '08:00', '18:00', 60)", [a, b])
        cur.execute("INSERT INTO forecasts (participant_id, ts, run_date, model_version) VALUES "
                    "(%s, %s, '2098-12-31', 'test'), (%s, %s, '2098-12-31', 'test')",
                    [a, d["ts"], b, d["ts"]])
        cur.execute("INSERT INTO advice (participant_id, advice_date, rank, appliance_category, "
                    "suggested_start, suggested_end, impact, expected_shared_kwh) VALUES "
                    "(%s, '2099-01-01', 1, 'transport', %s, %s, 'high', 6), "
                    "(%s, '2099-01-01', 1, 'transport', %s, %s, 'high', 6)",
                    [a, d["ts"], d["ts_end"], b, d["ts"], d["ts_end"]])
        cur.execute("INSERT INTO community_simultaneity VALUES (%s, 1, 2, 1, 2) "
                    "ON CONFLICT DO NOTHING", [d["ts"]])
        cur.execute("INSERT INTO energy_prices VALUES (%s, 0.25) ON CONFLICT DO NOTHING", [d["ts"]])
    return d


# ---------------------------------------------------------------------------
# 1. Rollen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(EXPECTED_ATTRIBUTES))
def test_rol_bestaat_met_juiste_eigenschappen(conn, role):
    rows = query(conn, "SELECT rolcanlogin, rolinherit, rolbypassrls, rolcreaterole "
                       "FROM pg_roles WHERE rolname = %s", [role])
    assert rows, f"Rol {role} bestaat niet"
    login, inherit, bypassrls, createrole = rows[0]
    exp_login, exp_inherit, exp_bypass, exp_create = EXPECTED_ATTRIBUTES[role]
    assert login == exp_login, f"{role}: inloggen hoort {exp_login} te zijn"
    assert inherit == exp_inherit, f"{role}: erven van rechten hoort {exp_inherit} te zijn"
    assert bypassrls == exp_bypass, f"{role}: BYPASSRLS hoort {exp_bypass} te zijn"
    assert createrole == exp_create, f"{role}: CREATEROLE hoort {exp_create} te zijn"


@pytest.mark.parametrize("login_role", list(EXPECTED_SET_ROLE))
def test_inlogrol_mag_alleen_naar_eigen_groepsrollen_wisselen(conn, login_role):
    for group, expected in EXPECTED_SET_ROLE[login_role].items():
        actual = query(conn, "SELECT pg_has_role(%s, %s, 'SET')", [login_role, group])[0][0]
        assert actual == expected, f"{login_role} -> SET ROLE {group}: verwacht {expected}"


def test_ses_dba_is_eigenaar_en_beheert_rollen(conn):
    assert query(conn, "SELECT pg_has_role('ses_dba', 'ses_owner', 'USAGE')")[0][0], \
        "ses_dba hoort de rechten van ses_owner te hebben"
    for role in GROUP_ROLES + ["ses_frontend", "ses_backend", "ses_backup"]:
        admin = query(conn, "SELECT pg_has_role('ses_dba', %s, 'MEMBER WITH ADMIN OPTION')", [role])[0][0]
        assert admin, f"ses_dba hoort {role} te mogen beheren (ADMIN OPTION)"


def test_ses_backup_mag_alles_lezen(conn):
    assert query(conn, "SELECT pg_has_role('ses_backup', 'pg_read_all_data', 'USAGE')")[0][0]


@pytest.mark.parametrize("table", TABLES)
def test_tabel_is_van_ses_owner(conn, table):
    owner = query(conn, "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = %s", [table])
    assert owner, f"Tabel {table} bestaat niet"
    assert owner[0][0] == "ses_owner", f"{table} is van {owner[0][0]}, niet van ses_owner"


# ---------------------------------------------------------------------------
# 2. Rechtenmatrix
# ---------------------------------------------------------------------------


def _columns(conn, table):
    return [r[0] for r in query(conn, "SELECT column_name FROM information_schema.columns "
                                      "WHERE table_schema = 'public' AND table_name = %s", [table])]


@pytest.mark.parametrize("role", GROUP_ROLES)
@pytest.mark.parametrize("table", TABLES)
def test_rechten_kloppen_met_ontwerp(conn, table, role):
    expected = EXPECTED[table].get(role, {})
    columns = _columns(conn, table)
    errors = []

    for privilege in ["SELECT", "INSERT", "UPDATE"]:
        allowed = expected.get(privilege)
        allowed = set(columns) if allowed == ALL else (allowed or set())
        for column in columns:
            actual = query(conn, "SELECT has_column_privilege(%s, %s, %s, %s)",
                           [role, f"public.{table}", column, privilege])[0][0]
            if actual != (column in allowed):
                errors.append(f"{privilege} op {table}.{column}: verwacht "
                              f"{'toegestaan' if column in allowed else 'verboden'}")

    expected_delete = expected.get("DELETE", False)
    actual_delete = query(conn, "SELECT has_table_privilege(%s, %s, 'DELETE')",
                          [role, f"public.{table}"])[0][0]
    if actual_delete != expected_delete:
        errors.append(f"DELETE op {table}: verwacht {'toegestaan' if expected_delete else 'verboden'}")

    assert not errors, f"{role}:\n  " + "\n  ".join(errors)


@pytest.mark.parametrize("role", ["ses_frontend", "ses_backend"])
def test_inlogrol_heeft_zonder_rolwissel_geen_rechten(conn, role):
    for table in TABLES:
        for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE"]:
            has = query(conn, "SELECT has_table_privilege(%s, %s, %s)",
                        [role, f"public.{table}", privilege])[0][0]
            assert not has, f"{role} heeft direct {privilege} op {table}"


def test_niemand_kan_password_hash_lezen(conn):
    for role in GROUP_ROLES + ["ses_frontend", "ses_backend"]:
        can = query(conn, "SELECT has_column_privilege(%s, 'public.users', 'password_hash', 'SELECT')", [role])[0][0]
        assert not can, f"{role} kan password_hash lezen"


def test_inlogfunctie_alleen_voor_ses_frontend(conn):
    fn = "public.auth_user_by_email(text)"
    for role, expected in [("ses_frontend", True), ("ses_backend", False),
                           ("web_participant", False), ("web_admin", False)]:
        actual = query(conn, "SELECT has_function_privilege(%s, %s, 'EXECUTE')", [role, fn])[0][0]
        assert actual == expected, f"{role} EXECUTE op {fn}: verwacht {expected}"


# ---------------------------------------------------------------------------
# 3. Row-level security
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("table", RLS_TABLES)
def test_rls_staat_aan(conn, table):
    assert query(conn, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                 [f"public.{table}"])[0][0], f"RLS staat niet aan op {table}"


OWN_ROWS = {
    "participants": "SELECT DISTINCT id FROM participants",
    "users": "SELECT DISTINCT participant_id FROM users",
    "participant_appliances": "SELECT DISTINCT participant_id FROM participant_appliances",
    "meters": "SELECT DISTINCT participant_id FROM meters",
    "forecasts": "SELECT DISTINCT participant_id FROM forecasts",
    "advice": "SELECT DISTINCT participant_id FROM advice",
}


@pytest.mark.parametrize("table", list(OWN_ROWS))
def test_deelnemer_ziet_alleen_eigen_rijen(conn, data, table):
    with als(conn, "web_participant", data["a"]) as cur:
        cur.execute(OWN_ROWS[table])
        seen = {r[0] for r in cur.fetchall()}
    assert seen == {data["a"]}, f"Deelnemer A ziet in {table} rijen van: {seen}"


def test_deelnemer_ziet_alleen_eigen_metingen(conn, data):
    with als(conn, "web_participant", data["a"]) as cur:
        cur.execute("SELECT DISTINCT meter_reference FROM readings")
        seen = {r[0] for r in cur.fetchall()}
    assert seen == {data["meter_a"]}, f"Deelnemer A ziet metingen van: {seen}"


def test_viewer_ziet_geen_persoonlijke_data(conn, data):
    with als(conn, "web_participant") as cur:  # geen deelnemer gekoppeld
        for table in RLS_TABLES:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
                        if table != "users" else "SELECT count(id) FROM users")
            assert cur.fetchone()[0] == 0, f"Viewer ziet rijen in {table}"
        for table in ["community_simultaneity", "energy_prices"]:
            cur.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table)))
            assert cur.fetchone()[0] > 0, f"Viewer ziet geen rijen in {table}"


def test_beheerder_ziet_alle_deelnemers(conn, data):
    with als(conn, "web_admin") as cur:
        cur.execute("SELECT count(*) FROM advice WHERE participant_id IN (%s, %s)", [data["a"], data["b"]])
        assert cur.fetchone()[0] == 2


# ---------------------------------------------------------------------------
# 4. Gedrag
# ---------------------------------------------------------------------------


def test_deelnemer_geeft_alleen_feedback_op_eigen_advies(conn, data):
    with als(conn, "web_participant", data["a"]) as cur:
        cur.execute("UPDATE advice SET feedback = 'accepted' WHERE participant_id IN (%s, %s)",
                    [data["a"], data["b"]])
        assert cur.rowcount == 1, "Deelnemer A kon ook advies van B wijzigen"


def test_deelnemer_kan_advies_zelf_niet_wijzigen(conn, data):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with als(conn, "web_participant", data["a"]) as cur:
            cur.execute("UPDATE advice SET rank = 2 WHERE participant_id = %s", [data["a"]])


def test_deelnemer_past_alleen_eigen_comfortgrenzen_aan(conn, data):
    with als(conn, "web_participant", data["a"]) as cur:
        cur.execute("UPDATE participant_appliances SET latest_end = '19:00' "
                    "WHERE participant_id IN (%s, %s)", [data["a"], data["b"]])
        assert cur.rowcount == 1, "Deelnemer A kon ook apparaten van B wijzigen"


def test_deelnemer_kan_apparaat_niet_verplaatsen(conn, data):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with als(conn, "web_participant", data["a"]) as cur:
            cur.execute("UPDATE participant_appliances SET participant_id = %s WHERE participant_id = %s",
                        [data["b"], data["a"]])


@pytest.mark.parametrize("role", ["web_participant", "web_admin"])
def test_select_op_password_hash_faalt(conn, data, role):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with als(conn, role, data["a"]) as cur:
            cur.execute("SELECT password_hash FROM users")


def test_herhaalde_avondrun_behoudt_feedback(conn, data):
    # Feedback klaarzetten als superuser, zodat die tijdens deze test zichtbaar blijft
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT avondrun")
        cur.execute("UPDATE advice SET feedback = 'accepted' WHERE participant_id = %s", [data["a"]])
    try:
        with als(conn, "svc_forecast") as cur:
            cur.execute(
                "INSERT INTO advice (participant_id, advice_date, rank, appliance_category, "
                "suggested_start, suggested_end, impact, expected_shared_kwh) "
                "VALUES (%s, '2099-01-01', 1, 'heat_pump', %s, %s, 'low', 2) "
                "ON CONFLICT (participant_id, advice_date, rank) DO UPDATE SET "
                "appliance_category = EXCLUDED.appliance_category, impact = EXCLUDED.impact, "
                "expected_shared_kwh = EXCLUDED.expected_shared_kwh",
                [data["a"], data["ts"], data["ts_end"]])
            cur.execute("SELECT appliance_category, feedback FROM advice "
                        "WHERE participant_id = %s AND advice_date = '2099-01-01' AND rank = 1", [data["a"]])
            assert cur.fetchone() == ("heat_pump", "accepted")
    finally:
        with conn.cursor() as cur:
            cur.execute("ROLLBACK TO SAVEPOINT avondrun")


@pytest.mark.parametrize("role", ["svc_forecast", "svc_training"])
def test_service_kan_feedback_niet_wijzigen(conn, data, role):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with als(conn, role) as cur:
            cur.execute("UPDATE advice SET feedback = NULL WHERE participant_id = %s", [data["a"]])


def test_training_schrijft_gemeten_effect(conn, data):
    with als(conn, "svc_training") as cur:
        cur.execute("UPDATE advice SET measured_effect_kwh = 1.5 WHERE participant_id = %s", [data["a"]])
        assert cur.rowcount == 1


def test_processing_importeert_metingen_met_upsert(conn, data):
    with als(conn, "svc_processing") as cur:
        cur.execute("INSERT INTO readings VALUES (%s, %s, 5, 0) ON CONFLICT (meter_reference, ts) "
                    "DO UPDATE SET to_grid_kwh = EXCLUDED.to_grid_kwh", [data["meter_a"], data["ts"]])
        cur.execute("SELECT to_grid_kwh FROM readings WHERE meter_reference = %s AND ts = %s",
                    [data["meter_a"], data["ts"]])
        assert cur.fetchone()[0] == 5


def test_beheerder_koppelt_meter_aan_deelnemer(conn, data):
    with als(conn, "web_admin") as cur:
        cur.execute("UPDATE meters SET participant_id = %s WHERE meter_reference = %s",
                    [data["b"], data["meter_a"]])
        assert cur.rowcount == 1


def test_inlogfunctie_geeft_account_terug(conn, data):
    with conn.cursor() as cur:
        cur.execute("SAVEPOINT login")
        cur.execute("SET LOCAL ROLE ses_frontend")
        cur.execute("SELECT user_role, participant_id FROM auth_user_by_email(%s)", [data["email_a"]])
        row = cur.fetchone()
        cur.execute("ROLLBACK TO SAVEPOINT login")
    assert row == ("participant", data["a"])


# ---------------------------------------------------------------------------
# 5. Inloggen met de echte inlogrollen
# ---------------------------------------------------------------------------


def _connect_as(role):
    params = conninfo_to_dict(ADMIN_URL)
    params.update(user=role, password=LOGIN_PASSWORDS[role])
    return psycopg.connect(make_conninfo(**params), autocommit=True)


@pytest.mark.parametrize("role", LOGIN_ROLES)
def test_inlogrol_kan_inloggen(role):
    try:
        with _connect_as(role) as c:
            assert c.execute("SELECT current_user").fetchone()[0] == role
    except psycopg.OperationalError as e:
        pytest.fail(f"{role} kan niet inloggen. Is het wachtwoord gewijzigd? "
                    f"Zet dan SES_PASSWORD_{role.removeprefix('ses_').upper()}. Fout: {e}")


@pytest.mark.parametrize("login_role, group, allowed", [
    ("ses_frontend", "web_participant", True),
    ("ses_frontend", "web_admin", True),
    ("ses_frontend", "svc_forecast", False),
    ("ses_backend", "svc_processing", True),
    ("ses_backend", "svc_training", True),
    ("ses_backend", "svc_forecast", True),
    ("ses_backend", "web_admin", False),
])
def test_rolwissel_na_inloggen(login_role, group, allowed):
    with _connect_as(login_role) as c:
        if allowed:
            c.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(group)))
            assert c.execute("SELECT current_user").fetchone()[0] == group
        else:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(group)))
