"""Alembic runs this file: connect with DATABASE_URL and apply the migrations in versions/."""

import logging
import os

from alembic import context
from sqlalchemy import create_engine

logging.basicConfig(level=logging.INFO, format="%(message)s")

url = os.environ["DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)

with create_engine(url).connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
