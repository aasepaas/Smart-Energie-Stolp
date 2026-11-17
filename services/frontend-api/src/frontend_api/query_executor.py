"""Query executor (component 'Query executor' in C4 3.2).

The API logs in as ses_frontend (NOINHERIT: no table rights without a role switch).
Every request gets its own transaction in which the database role follows the
application role of the user:

    participant, viewer         -> SET LOCAL ROLE web_participant
    administrator, superadmin   -> SET LOCAL ROLE web_admin

For a participant `app.participant_id` is set as well, so row-level security only
returns their own rows. A viewer has no participant id and only sees community data.
A request that succeeds is committed; any error rolls everything back.
"""

from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from fastapi import Depends
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .authentication import Principal, current_user
from .config import DATABASE_URL

pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False)

Query = str | sql.Composable
Params = Sequence[Any] | Mapping[str, Any] | None


class Session:
    """Runs parameterised queries in the transaction of one request."""

    def __init__(self, cursor):
        self._cur = cursor

    def all(self, query: Query, params: Params = None) -> list[dict]:
        self._cur.execute(query, params)
        return self._cur.fetchall()

    def one(self, query: Query, params: Params = None) -> dict | None:
        self._cur.execute(query, params)
        return self._cur.fetchone()

    def execute(self, query: Query, params: Params = None) -> int:
        """Runs a write without result rows and returns the number of affected rows."""
        self._cur.execute(query, params)
        return self._cur.rowcount


def get_session(user: Principal = Depends(current_user)) -> Iterator[Session]:
    """Session with the rights of the logged in user.

    Always use Depends(get_session, scope="function"), so the transaction commits
    before the response is sent (same as the Backend API).
    """
    with pool.connection() as conn, conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(user.db_role)))
            cur.execute(
                "SELECT set_config('app.participant_id', %s, true)",
                [str(user.participant_id) if user.participant_id else ""],
            )
            yield Session(cur)


def get_login_session() -> Iterator[Session]:
    """Session without a role switch, for logging in and refreshing only.

    ses_frontend itself may only run the function auth_user_by_email; it cannot read
    any table. Use Depends(get_login_session, scope="function").
    """
    with pool.connection() as conn, conn.transaction():
        with conn.cursor(row_factory=dict_row) as cur:
            yield Session(cur)
