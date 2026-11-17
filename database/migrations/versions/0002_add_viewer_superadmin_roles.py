"""Add the application roles viewer and superadmin to user_role.

The Frontend API maps viewer to web_participant (without a participant) and
superadmin to web_admin; see database/roles/readme.md. No grants change.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

UPGRADE_SQL = """
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'viewer';
ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'superadmin';
"""

# PostgreSQL cannot remove enum values, so the type is rebuilt. The login function
# returns user_role and the check constraint compares with it, so both are dropped
# and recreated around it.
DOWNGRADE_SQL = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM users WHERE role::text IN ('viewer', 'superadmin')) THEN
    RAISE EXCEPTION 'Delete or change viewer and superadmin accounts before the downgrade';
  END IF;
END
$$;

DROP FUNCTION auth_user_by_email(text);
ALTER TABLE users DROP CONSTRAINT users_participant_role_check;
ALTER TYPE user_role RENAME TO user_role_0002;
CREATE TYPE user_role AS ENUM ('participant', 'administrator');
ALTER TYPE user_role OWNER TO ses_owner;
ALTER TABLE users ALTER COLUMN role TYPE user_role USING role::text::user_role;
DROP TYPE user_role_0002;
ALTER TABLE users ADD CONSTRAINT users_participant_role_check
  CHECK ((role = 'participant') = (participant_id IS NOT NULL));

CREATE FUNCTION auth_user_by_email(p_email text)
  RETURNS TABLE (user_id uuid, password_hash varchar, user_role user_role, participant_id uuid)
  LANGUAGE sql STABLE SECURITY DEFINER
  SET search_path = public, pg_temp
  AS $f$
    SELECT u.id, u.password_hash, u.role, u.participant_id
    FROM users u
    WHERE u.email = p_email
  $f$;
ALTER FUNCTION auth_user_by_email(text) OWNER TO ses_owner;
REVOKE EXECUTE ON FUNCTION auth_user_by_email(text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION auth_user_by_email(text) TO ses_frontend;
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
