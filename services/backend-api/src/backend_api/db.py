"""Database connection.

De API logs in as ses_backend (NOINHERIT: zonder rolwissel geen rechten).
each request gets its own transaction where the database rol gets determined based
on which service is connected(decided by auth.py). successful request then execute;
not successful nothing happens to the database.
"""

from fastapi import Depends
from psycopg import sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .auth import Service, current_service
from .config import DATABASE_URL

pool = ConnectionPool(DATABASE_URL, min_size=1, max_size=10, open=False)


def get_cursor(service: Service = Depends(current_service)):
    with pool.connection() as conn:
        with conn.transaction():
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(service.db_role))
                )
                yield cur
