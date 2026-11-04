"""Initial schema, roles and permissions.

Schema: database/erd/ses-database.dbml
Roles and permissions: database/roles/readme.md

Revision ID: 0001
Revises:
Create Date: 2026-11-04
"""

import os

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

# Login roles and the environment variable that holds their password.
# Without the variable the role gets no password and cannot log in.
LOGIN_PASSWORDS = {
    "ses_dba": "SES_PASSWORD_DBA",
    "ses_frontend": "SES_PASSWORD_FRONTEND",
    "ses_backend": "SES_PASSWORD_BACKEND",
    "ses_backup": "SES_PASSWORD_BACKUP",
}


SCHEMA_SQL = """
-- ─────────── Enums ───────────

CREATE TYPE user_role AS ENUM ('participant', 'administrator');
CREATE TYPE appliance_category AS ENUM ('transport', 'heat_pump', 'air_conditioning');
CREATE TYPE impact_class AS ENUM ('high', 'medium', 'low');
CREATE TYPE advice_feedback AS ENUM ('accepted', 'rejected');
CREATE TYPE import_status AS ENUM ('running', 'succeeded', 'failed');

-- ─────────── Participants and accounts ───────────

CREATE TABLE participants (
    id   uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar(100) NOT NULL UNIQUE
);

CREATE TABLE users (
    id             uuid         PRIMARY KEY DEFAULT gen_random_uuid(),
    email          varchar(255) NOT NULL UNIQUE,
    password_hash  varchar(255) NOT NULL,
    role           user_role    NOT NULL,
    participant_id uuid         REFERENCES participants (id) ON DELETE CASCADE,
    -- a participant account must point to a participant, an administrator account must not
    CONSTRAINT users_participant_role_check
        CHECK ((role = 'participant') = (participant_id IS NOT NULL))
);
CREATE INDEX users_participant_id_idx ON users (participant_id);

CREATE TABLE participant_appliances (
    id              uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_id  uuid               NOT NULL REFERENCES participants (id) ON DELETE CASCADE,
    category        appliance_category NOT NULL,
    power_kw        numeric(6, 2)      NOT NULL CHECK (power_kw > 0),
    -- comfort window; may cross midnight (for example EV charging 22:00 to 07:00)
    earliest_start  time               NOT NULL,
    latest_end      time               NOT NULL,
    min_run_minutes smallint           NOT NULL CHECK (min_run_minutes > 0),
    UNIQUE (participant_id, category)
);

CREATE TABLE settings (
    key        varchar(100) PRIMARY KEY,
    value      jsonb        NOT NULL,
    updated_at timestamptz  NOT NULL DEFAULT now()
);

-- ─────────── Meter data ───────────

CREATE TABLE import_log (
    id              uuid          PRIMARY KEY DEFAULT gen_random_uuid(),
    file_name       varchar(255)  NOT NULL,
    file_hash       char(64)      NOT NULL UNIQUE,  -- SHA-256 of the uploaded file
    period_start    timestamptz,
    period_end      timestamptz,
    row_count       integer       CHECK (row_count >= 0),
    new_meter_count integer       CHECK (new_meter_count >= 0),
    status          import_status NOT NULL DEFAULT 'running',
    error_message   text,
    started_at      timestamptz   NOT NULL DEFAULT now(),
    CHECK (period_end >= period_start)
);

CREATE TABLE meters (
    meter_reference varchar(64) PRIMARY KEY,  -- KV01, GV03 or meter_ + 24 hex
    participant_id  uuid        REFERENCES participants (id) ON DELETE SET NULL
);
CREATE INDEX meters_participant_id_idx ON meters (participant_id);

CREATE TABLE readings (
    meter_reference varchar(64)    NOT NULL REFERENCES meters (meter_reference) ON DELETE RESTRICT,
    ts              timestamptz    NOT NULL,  -- start of the quarter hour, UTC
    to_grid_kwh     numeric(10, 3) NOT NULL CHECK (to_grid_kwh >= 0),
    from_grid_kwh   numeric(10, 3) NOT NULL CHECK (from_grid_kwh >= 0),
    PRIMARY KEY (meter_reference, ts)
);

-- ─────────── Results ───────────

CREATE TABLE community_simultaneity (
    ts                  timestamptz    PRIMARY KEY,
    total_to_grid_kwh   numeric(10, 3) NOT NULL CHECK (total_to_grid_kwh >= 0),
    total_from_grid_kwh numeric(10, 3) NOT NULL CHECK (total_from_grid_kwh >= 0),
    shared_kwh          numeric(10, 3) NOT NULL,
    meter_count         smallint       NOT NULL CHECK (meter_count >= 0),
    CONSTRAINT community_simultaneity_shared_check
        CHECK (shared_kwh = LEAST(total_to_grid_kwh, total_from_grid_kwh))
);

CREATE TABLE forecasts (
    participant_id uuid           NOT NULL REFERENCES participants (id) ON DELETE CASCADE,
    ts             timestamptz    NOT NULL,  -- quarter hour the forecast is about
    run_date       date           NOT NULL,  -- evening the forecast was made
    to_grid_p10    numeric(10, 3),
    to_grid_p50    numeric(10, 3),
    to_grid_p90    numeric(10, 3),
    from_grid_p10  numeric(10, 3),
    from_grid_p50  numeric(10, 3),
    from_grid_p90  numeric(10, 3),
    model_version  varchar(100)   NOT NULL,
    PRIMARY KEY (participant_id, ts, run_date)
);

CREATE TABLE energy_prices (
    ts                timestamptz   PRIMARY KEY,
    price_eur_per_kwh numeric(8, 5) NOT NULL  -- can be negative
);

CREATE TABLE advice (
    id                     uuid               PRIMARY KEY DEFAULT gen_random_uuid(),
    participant_id         uuid               NOT NULL REFERENCES participants (id) ON DELETE CASCADE,
    advice_date            date               NOT NULL,
    rank                   smallint           NOT NULL CHECK (rank BETWEEN 1 AND 3),
    appliance_category     appliance_category NOT NULL,
    suggested_start        timestamptz        NOT NULL,
    suggested_end          timestamptz        NOT NULL,
    impact                 impact_class       NOT NULL,
    expected_shared_kwh    numeric(10, 3)     NOT NULL,
    acceptance_probability numeric(4, 3)      CHECK (acceptance_probability BETWEEN 0 AND 1),
    feedback               advice_feedback,
    measured_effect_kwh    numeric(10, 3),
    UNIQUE (participant_id, advice_date, rank),
    CHECK (suggested_end > suggested_start)
);

-- ─────────── TimescaleDB hypertables ───────────
-- Small data volume (about 3,700 readings per day), so one chunk per month.

SELECT create_hypertable('readings',               by_range('ts', INTERVAL '1 month'));
SELECT create_hypertable('community_simultaneity', by_range('ts', INTERVAL '1 month'));
SELECT create_hypertable('forecasts',              by_range('ts', INTERVAL '1 month'));
SELECT create_hypertable('energy_prices',          by_range('ts', INTERVAL '1 month'));
"""

ROLES_SQL = """
-- =====================================================================
-- Rollen en rechten (ontwerp en rechtenmatrix: database/roles/readme.md)
-- Legenda README:  R = SELECT  I = INSERT  W = UPDATE  D = DELETE
-- Wachtwoorden van de inlogrollen staan niet hier maar komen uit
-- omgevingsvariabelen (zie set_login_passwords hieronder).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Rollen aanmaken
--    Rollen gelden voor de hele PostgreSQL-server en blijven bestaan na een
--    downgrade, dus ze worden alleen aangemaakt als ze nog niet bestaan.
-- ---------------------------------------------------------------------

DO $$
DECLARE
  r record;
BEGIN
  FOR r IN SELECT * FROM (VALUES
    -- Eigenaar van alle tabellen (kan niet inloggen)
    ('ses_owner',       'NOLOGIN'),
    -- Databasebeheerder: beheert alles omtrent de database
    ('ses_dba',         'LOGIN CREATEROLE CREATEDB'),
    -- Groepsrollen zonder inlogrecht (hier zitten de rechten op)
    ('web_participant', 'NOLOGIN'),   -- participant en viewer
    ('web_admin',       'NOLOGIN'),   -- administrator en superadmin (applicatie)
    ('svc_processing',  'NOLOGIN'),   -- Data processing service
    ('svc_training',    'NOLOGIN'),   -- Ingest and training pipeline
    ('svc_forecast',    'NOLOGIN'),   -- Forecast pipeline
    -- Inlogrollen van de API's. NOINHERIT: zonder SET ROLE hebben ze
    -- geen rechten op tabellen, dus elk verzoek moet een groepsrol kiezen.
    ('ses_frontend',    'LOGIN NOINHERIT'),
    ('ses_backend',     'LOGIN NOINHERIT'),
    -- Back-ups met pg_dump. BYPASSRLS is nodig: pg_dump weigert tabellen
    -- waarop row-level security de rijen zou beperken.
    ('ses_backup',      'LOGIN BYPASSRLS')
  ) AS t(name, options)
  LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r.name) THEN
      EXECUTE format('CREATE ROLE %I %s', r.name, r.options);
    END IF;
  END LOOP;
END
$$;

-- Lidmaatschappen
GRANT web_participant, web_admin TO ses_frontend;
GRANT svc_processing, svc_training, svc_forecast TO ses_backend;
GRANT pg_read_all_data TO ses_backup;

-- ses_dba werkt als eigenaar van de tabellen ...
GRANT ses_owner TO ses_dba;
-- ... en mag alle SES-rollen beheren (wachtwoorden, rechten),
-- zonder zelf hun rechten te krijgen.
GRANT web_participant, web_admin, svc_processing, svc_training, svc_forecast,
      ses_frontend, ses_backend, ses_backup
  TO ses_dba WITH ADMIN TRUE, INHERIT FALSE, SET FALSE;

-- ---------------------------------------------------------------------
-- 2. Database en schema
--    De naam van de database staat niet vast (current_database()).
-- ---------------------------------------------------------------------

DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I OWNER TO ses_owner', current_database());
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO ses_dba, ses_frontend, ses_backend, ses_backup',
                 current_database());
END
$$;

ALTER SCHEMA public OWNER TO ses_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public
  TO web_participant, web_admin, svc_processing, svc_training, svc_forecast,
     ses_frontend;   -- ses_frontend direct, voor de inlogfunctie

-- ---------------------------------------------------------------------
-- 3. Eigenaarschap van tabellen en types naar ses_owner
-- ---------------------------------------------------------------------

ALTER TABLE participants           OWNER TO ses_owner;
ALTER TABLE users                  OWNER TO ses_owner;
ALTER TABLE participant_appliances OWNER TO ses_owner;
ALTER TABLE settings               OWNER TO ses_owner;
ALTER TABLE import_log             OWNER TO ses_owner;
ALTER TABLE meters                 OWNER TO ses_owner;
ALTER TABLE readings               OWNER TO ses_owner;
ALTER TABLE community_simultaneity OWNER TO ses_owner;
ALTER TABLE forecasts              OWNER TO ses_owner;
ALTER TABLE energy_prices          OWNER TO ses_owner;
ALTER TABLE advice                 OWNER TO ses_owner;

ALTER TYPE user_role          OWNER TO ses_owner;
ALTER TYPE appliance_category OWNER TO ses_owner;
ALTER TYPE impact_class       OWNER TO ses_owner;
ALTER TYPE advice_feedback    OWNER TO ses_owner;
ALTER TYPE import_status      OWNER TO ses_owner;

-- ---------------------------------------------------------------------
-- 4. Tabelrechten (volgens de matrix in README.md)
-- ---------------------------------------------------------------------

-- participants:  web_participant R eigen | web_admin R I W D | training R | forecast R
GRANT SELECT                         ON participants TO web_participant;
GRANT SELECT, INSERT, UPDATE, DELETE ON participants TO web_admin;
GRANT SELECT                         ON participants TO svc_training, svc_forecast;

-- users:  web_participant R eigen | web_admin R I W D   (nooit password_hash lezen)
GRANT SELECT (id, email, role, participant_id) ON users TO web_participant, web_admin;
GRANT INSERT (id, email, password_hash, role, participant_id),
      UPDATE (email, password_hash, role, participant_id),
      DELETE
  ON users TO web_admin;

-- participant_appliances:  web_participant R W eigen | web_admin R I W D | forecast R
GRANT SELECT ON participant_appliances TO web_participant;
GRANT UPDATE (power_kw, earliest_start, latest_end, min_run_minutes)
  ON participant_appliances TO web_participant;   -- alleen comfortgrenzen, niet de eigenaar
GRANT SELECT, INSERT, UPDATE, DELETE ON participant_appliances TO web_admin;
GRANT SELECT ON participant_appliances TO svc_forecast;

-- settings:  web_admin R I W | processing, training, forecast R
GRANT SELECT, INSERT, UPDATE ON settings TO web_admin;
GRANT SELECT ON settings TO svc_processing, svc_training, svc_forecast;

-- import_log:  web_admin R I W | processing R I W
GRANT SELECT, INSERT, UPDATE ON import_log TO web_admin, svc_processing;

-- meters:  web_participant R eigen | web_admin R, W alleen participant_id | processing R I | training, forecast R
GRANT SELECT ON meters TO web_participant, web_admin, svc_training, svc_forecast;
GRANT UPDATE (participant_id) ON meters TO web_admin;
GRANT SELECT, INSERT ON meters TO svc_processing;

-- readings:  web_participant R eigen | web_admin R | processing R I W | training, forecast R
GRANT SELECT ON readings TO web_participant, web_admin, svc_training, svc_forecast;
GRANT SELECT, INSERT, UPDATE ON readings TO svc_processing;

-- community_simultaneity:  iedereen R | processing R I W D
GRANT SELECT ON community_simultaneity
  TO web_participant, web_admin, svc_training, svc_forecast;
GRANT SELECT, INSERT, UPDATE, DELETE ON community_simultaneity TO svc_processing;

-- forecasts:  web_participant R eigen | web_admin R | training R | forecast R I
GRANT SELECT ON forecasts TO web_participant, web_admin, svc_training;
GRANT SELECT, INSERT ON forecasts TO svc_forecast;

-- energy_prices:  web_participant, web_admin R | forecast R I W
GRANT SELECT ON energy_prices TO web_participant, web_admin;
GRANT SELECT, INSERT, UPDATE ON energy_prices TO svc_forecast;

-- advice:  web_participant R eigen, W feedback | web_admin R | training R, W measured_effect_kwh | forecast R I W D
GRANT SELECT ON advice TO web_participant, web_admin, svc_training;
GRANT UPDATE (feedback) ON advice TO web_participant;
GRANT UPDATE (measured_effect_kwh) ON advice TO svc_training;
GRANT SELECT, INSERT, DELETE ON advice TO svc_forecast;
-- W alleen op de adviesvelden, zodat een herhaalde avondrun (upsert op
-- participant_id, advice_date, rank) nooit feedback of gemeten effect overschrijft
GRANT UPDATE (appliance_category, suggested_start, suggested_end, impact,
              expected_shared_kwh, acceptance_probability)
  ON advice TO svc_forecast;

-- ---------------------------------------------------------------------
-- 5. Hulpfunctie: de ingelogde deelnemer
--    De Frontend API zet per verzoek: SET LOCAL app.participant_id = '<uuid>'
--    Leeg of niet gezet (viewer, beheerder) geeft NULL: dan geen eigen rijen.
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION app_participant_id() RETURNS uuid
  LANGUAGE sql STABLE
  AS $$ SELECT NULLIF(current_setting('app.participant_id', true), '')::uuid $$;
ALTER FUNCTION app_participant_id() OWNER TO ses_owner;

-- ---------------------------------------------------------------------
-- 6. Row-level security
--    Alleen web_participant wordt beperkt tot eigen rijen. Voor web_admin
--    en de services laat RLS alle rijen door; wat zij mogen doen,
--    bepalen de GRANTs hierboven.
-- ---------------------------------------------------------------------

ALTER TABLE participants           ENABLE ROW LEVEL SECURITY;
ALTER TABLE users                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE participant_appliances ENABLE ROW LEVEL SECURITY;
ALTER TABLE meters                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE readings               ENABLE ROW LEVEL SECURITY;
ALTER TABLE forecasts              ENABLE ROW LEVEL SECURITY;
ALTER TABLE advice                 ENABLE ROW LEVEL SECURITY;

-- participants
CREATE POLICY own_select ON participants FOR SELECT TO web_participant
  USING (id = app_participant_id());
CREATE POLICY all_rows ON participants FOR ALL
  TO web_admin, svc_training, svc_forecast
  USING (true) WITH CHECK (true);

-- users
CREATE POLICY own_select ON users FOR SELECT TO web_participant
  USING (participant_id = app_participant_id());
CREATE POLICY all_rows ON users FOR ALL TO web_admin
  USING (true) WITH CHECK (true);

-- participant_appliances
CREATE POLICY own_select ON participant_appliances FOR SELECT TO web_participant
  USING (participant_id = app_participant_id());
CREATE POLICY own_update ON participant_appliances FOR UPDATE TO web_participant
  USING (participant_id = app_participant_id())
  WITH CHECK (participant_id = app_participant_id());
CREATE POLICY all_rows ON participant_appliances FOR ALL
  TO web_admin, svc_forecast
  USING (true) WITH CHECK (true);

-- meters
CREATE POLICY own_select ON meters FOR SELECT TO web_participant
  USING (participant_id = app_participant_id());
CREATE POLICY all_rows ON meters FOR ALL
  TO web_admin, svc_processing, svc_training, svc_forecast
  USING (true) WITH CHECK (true);

-- readings (eigen = van een meter die aan de deelnemer is gekoppeld)
CREATE POLICY own_select ON readings FOR SELECT TO web_participant
  USING (meter_reference IN (
    SELECT m.meter_reference FROM meters m
    WHERE m.participant_id = app_participant_id()
  ));
CREATE POLICY all_rows ON readings FOR ALL
  TO web_admin, svc_processing, svc_training, svc_forecast
  USING (true) WITH CHECK (true);

-- forecasts
CREATE POLICY own_select ON forecasts FOR SELECT TO web_participant
  USING (participant_id = app_participant_id());
CREATE POLICY all_rows ON forecasts FOR ALL
  TO web_admin, svc_training, svc_forecast
  USING (true) WITH CHECK (true);

-- advice
CREATE POLICY own_select ON advice FOR SELECT TO web_participant
  USING (participant_id = app_participant_id());
CREATE POLICY own_update ON advice FOR UPDATE TO web_participant
  USING (participant_id = app_participant_id())
  WITH CHECK (participant_id = app_participant_id());
CREATE POLICY all_rows ON advice FOR ALL
  TO web_admin, svc_training, svc_forecast
  USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------------
-- 7. Inlogfunctie
--    Geen enkele rol mag password_hash lezen. Bij het inloggen roept de
--    Frontend API (als ses_frontend, nog zonder SET ROLE) deze functie aan
--    en controleert de hash zelf (bijvoorbeeld met argon2 of bcrypt).
-- ---------------------------------------------------------------------

CREATE OR REPLACE FUNCTION auth_user_by_email(p_email text)
  RETURNS TABLE (user_id uuid, password_hash varchar, user_role user_role, participant_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = public, pg_temp
  AS $$
    SELECT u.id, u.password_hash, u.role, u.participant_id
    FROM users u
    WHERE u.email = p_email
  $$;
ALTER FUNCTION auth_user_by_email(text) OWNER TO ses_owner;
REVOKE EXECUTE ON FUNCTION auth_user_by_email(text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION auth_user_by_email(text) TO ses_frontend;
"""

DOWNGRADE_SQL = """
DROP TABLE IF EXISTS advice;
DROP TABLE IF EXISTS energy_prices;
DROP TABLE IF EXISTS forecasts;
DROP TABLE IF EXISTS community_simultaneity;
DROP TABLE IF EXISTS readings;
DROP TABLE IF EXISTS meters;
DROP TABLE IF EXISTS import_log;
DROP TABLE IF EXISTS settings;
DROP TABLE IF EXISTS participant_appliances;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS participants;

-- Rechten en policies zijn met de tabellen verdwenen; de rollen blijven bestaan.
DROP FUNCTION IF EXISTS auth_user_by_email(text);
DROP FUNCTION IF EXISTS app_participant_id();

DROP TYPE IF EXISTS import_status;
DROP TYPE IF EXISTS advice_feedback;
DROP TYPE IF EXISTS impact_class;
DROP TYPE IF EXISTS appliance_category;
DROP TYPE IF EXISTS user_role;

-- Database en schema terug naar de standaard van PostgreSQL
DO $$
BEGIN
  EXECUTE format('ALTER DATABASE %I OWNER TO %I', current_database(), current_user);
  EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM ses_dba, ses_frontend, ses_backend, ses_backup',
                 current_database());
  EXECUTE format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO PUBLIC', current_database());
END
$$;

ALTER SCHEMA public OWNER TO pg_database_owner;
REVOKE USAGE ON SCHEMA public
  FROM web_participant, web_admin, svc_processing, svc_training, svc_forecast, ses_frontend;
GRANT USAGE ON SCHEMA public TO PUBLIC;
"""


def set_login_passwords() -> None:
    connection = op.get_bind()
    for role, variable in LOGIN_PASSWORDS.items():
        password = os.environ.get(variable)
        if password:
            literal = "'" + password.replace("'", "''") + "'"
            # % is the placeholder character of the driver, so it is doubled
            statement = f"ALTER ROLE {role} PASSWORD {literal}".replace("%", "%%")
            connection.exec_driver_sql(statement)


def upgrade() -> None:
    op.execute(SCHEMA_SQL)
    op.execute(ROLES_SQL)
    set_login_passwords()


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
