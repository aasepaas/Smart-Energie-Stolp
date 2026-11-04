-- =====================================================================
-- Smart Energie Stolp (SES): rollen en rechten
--
-- Database:  PostgreSQL 16 of hoger, met TimescaleDB
-- Uitvoeren: als de PostgreSQL-superuser uit Docker (POSTGRES_USER),
--            in de database "ses", NADAT alle tabellen zijn aangemaakt.
--
--   psql -U postgres -d ses -v ON_ERROR_STOP=1 -f rollen_en_rechten.sql
--
-- Wachtwoorden: alle inlogrollen krijgen tijdelijk het wachtwoord 'user'.
-- Wijzig ze direct na het uitvoeren, bijvoorbeeld:
--   ALTER ROLE ses_frontend PASSWORD '<nieuw wachtwoord>';
-- en zet de echte wachtwoorden niet in Git (gebruik het .env-bestand).
--
-- Legenda README:  R = SELECT  I = INSERT  W = UPDATE  D = DELETE
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Rollen aanmaken
-- ---------------------------------------------------------------------

-- Eigenaar van alle tabellen (kan niet inloggen)
CREATE ROLE ses_owner NOLOGIN;

-- Databasebeheerder: beheert alles omtrent de database
CREATE ROLE ses_dba LOGIN CREATEROLE CREATEDB PASSWORD 'user';

-- Groepsrollen zonder inlogrecht (hier zitten de rechten op)
CREATE ROLE web_participant NOLOGIN;   -- participant en viewer
CREATE ROLE web_admin       NOLOGIN;   -- administrator en superadmin (applicatie)
CREATE ROLE svc_processing  NOLOGIN;   -- Data processing service
CREATE ROLE svc_training    NOLOGIN;   -- Ingest and training pipeline
CREATE ROLE svc_forecast    NOLOGIN;   -- Forecast pipeline

-- Inlogrollen van de API's. NOINHERIT: zonder SET ROLE hebben ze
-- geen rechten op tabellen, dus elk verzoek moet een groepsrol kiezen.
CREATE ROLE ses_frontend LOGIN NOINHERIT PASSWORD 'user';
CREATE ROLE ses_backend  LOGIN NOINHERIT PASSWORD 'user';

-- Back-ups met pg_dump. BYPASSRLS is nodig: pg_dump weigert tabellen
-- waarop row-level security de rijen zou beperken.
CREATE ROLE ses_backup LOGIN BYPASSRLS PASSWORD 'user';

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
-- ---------------------------------------------------------------------

ALTER DATABASE ses OWNER TO ses_owner;
REVOKE ALL ON DATABASE ses FROM PUBLIC;
GRANT CONNECT ON DATABASE ses TO ses_dba, ses_frontend, ses_backend, ses_backup;

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

CREATE FUNCTION app_participant_id() RETURNS uuid
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

CREATE FUNCTION auth_user_by_email(p_email text)
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

-- ---------------------------------------------------------------------
-- 8. Tabellen die later met migraties worden toegevoegd
--    Nieuwe tabellen krijgen standaard GEEN rechten; voeg ze per tabel
--    toe aan dit script en aan de matrix in README.md.
-- ---------------------------------------------------------------------

COMMIT;