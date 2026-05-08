"""Alembic environment.

Async migrations runner. Uses the same `asyncpg` driver the bot uses at
runtime — there is no second sync DBAPI in this project.

History: this used to import ``psycopg2`` and build a sync engine, which
made ``psycopg2-binary`` an implicit, easy-to-miss dependency (see
BUG-004 / TECH-008 in `backlog.md`). The current implementation runs
``do_run_migrations`` inside ``connection.run_sync(...)``, which is the
canonical async pattern from the SQLAlchemy / Alembic docs.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from src.config import settings  # noqa: E402
from src.database.base import Base  # noqa: E402
from src.database.models import *  # noqa: E402,F401,F403 — register models with Base

config = context.config

config.set_main_option("sqlalchemy.url", settings.get_async_database_url())

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without opening a DB connection."""
    context.configure(
        url=settings.get_async_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Open an async asyncpg connection and run sync migrations on top of it."""
    connectable = create_async_engine(
        settings.get_async_database_url(),
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
