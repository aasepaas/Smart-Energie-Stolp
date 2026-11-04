"""Initial schema, based on database/erd/ses-database.dbml.

Revision ID: 0001
Revises:
Create Date: 2026-11-04
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


UPGRADE_SQL = """
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

DROP TYPE IF EXISTS import_status;
DROP TYPE IF EXISTS advice_feedback;
DROP TYPE IF EXISTS impact_class;
DROP TYPE IF EXISTS appliance_category;
DROP TYPE IF EXISTS user_role;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
