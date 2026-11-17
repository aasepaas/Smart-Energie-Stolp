"""Create an account from the command line (for example the first administrator).

    python -m frontend_api.create_user admin@example.org
    python -m frontend_api.create_user p01@example.org --role participant --participant-id <uuid>

The password comes from SES_USER_PASSWORD, or is asked for when that is not set.
Connects with FRONTEND_DATABASE_URL and acts as web_admin, like an administrator in
the web app, but without the account rules of the API (this is an operator tool).
"""

import argparse
import getpass
import os
import sys
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from pydantic import ValidationError

from . import authentication, config, query_builder
from .query_executor import Session
from .schemas import NewUser


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m frontend_api.create_user",
                                     description="Create an SES account")
    parser.add_argument("email")
    parser.add_argument("--role", default="administrator", choices=authentication.ROLES)
    parser.add_argument("--participant-id", type=UUID, default=None)
    args = parser.parse_args(argv)

    password = os.environ.get("SES_USER_PASSWORD") or getpass.getpass("Password: ")
    try:
        user = NewUser(email=args.email, password=password, role=args.role,
                       participant_id=args.participant_id)
    except ValidationError as exc:
        print(f"Invalid account: {exc.errors()[0]['msg']}", file=sys.stderr)
        return 1

    try:
        with psycopg.connect(config.DATABASE_URL) as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET ROLE web_admin")
            row = query_builder.create_user(
                Session(cur), user.email, authentication.hash_password(user.password),
                user.role, user.participant_id,
            )
    except psycopg.errors.UniqueViolation:
        print(f"An account for {user.email} already exists", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        print(f"Account not created: {exc.diag.message_primary or exc}", file=sys.stderr)
        return 1
    print(f"Created {row['role']} account {row['email']} ({row['id']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
